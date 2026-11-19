-- Let Studio securely connect its configured MCP host to a workspace. The
-- generated token is encrypted in engine_secrets and never shown to a browser.
alter table public.workspace_mcp_tokens add constraint workspace_mcp_tokens_workspace_id_id_unique unique(workspace_id,id);
alter table public.engine_connections add column endpoint_url text not null default '';
alter table public.engine_connections add column mcp_token_id uuid;
alter table public.engine_connections add constraint engine_connection_token_workspace_fk
  foreign key(workspace_id,mcp_token_id) references public.workspace_mcp_tokens(workspace_id,id);

create function public.store_studio_engine_connection(
  target_workspace_id uuid,
  target_label text,
  target_endpoint_url text,
  actor_id uuid,
  presented_hash bytea,
  token_expires_at timestamptz,
  encrypted_payload bytea,
  encryption_version text
) returns uuid language plpgsql security definer set search_path=''
as $$
declare new_connection_id uuid; new_token_id uuid;
begin
  if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
  if not exists(select 1 from public.workspace_members m where m.workspace_id=target_workspace_id and m.user_id=actor_id and m.role in ('owner','admin')) then
    raise exception 'workspace owner or admin required' using errcode='42501';
  end if;
  if length(trim(target_label)) not between 1 and 120 then raise exception 'invalid engine label'; end if;
  if target_endpoint_url !~ '^https://[^/@?#[:space:]]+(/[^?#[:space:]]*)?$'
     and target_endpoint_url !~ '^http://(localhost|127[.]0[.]0[.]1|\[::1\])(:[0-9]+)?(/[^?#[:space:]]*)?$' then
    raise exception 'invalid MCP endpoint';
  end if;
  if octet_length(presented_hash)<>32 or octet_length(encrypted_payload)<29 then raise exception 'invalid engine secret'; end if;
  if encryption_version<>'aes-256-gcm-v1' then raise exception 'unsupported encryption version'; end if;
  if token_expires_at<=now() or token_expires_at>now()+interval '366 days' then raise exception 'engine token expiry is invalid'; end if;

  insert into public.workspace_mcp_tokens(workspace_id,label,token_hash,scopes,created_by,expires_at)
    values(target_workspace_id,'studio-engine:'||trim(target_label),presented_hash,array['mcp:read','mcp:write'],actor_id,token_expires_at)
    returning id into new_token_id;
  insert into public.engine_connections(workspace_id,label,status,endpoint_url,mcp_token_id,created_by)
    values(target_workspace_id,trim(target_label),'pending',target_endpoint_url,new_token_id,actor_id)
    returning id into new_connection_id;
  insert into public.engine_secrets(connection_id,workspace_id,ciphertext,key_version)
    values(new_connection_id,target_workspace_id,encrypted_payload,encryption_version);
  insert into public.audit_events(workspace_id,actor_id,action,subject_type,subject_id,metadata)
    values(target_workspace_id,actor_id,'studio.engine_connection.created','engine_connection',new_connection_id::text,
      jsonb_build_object('label',trim(target_label),'endpoint',target_endpoint_url));
  return new_connection_id;
end; $$;

create function public.sync_studio_engine_capabilities(
  target_connection_id uuid,
  target_capabilities jsonb
) returns integer language plpgsql security definer set search_path=''
as $$
declare target_workspace_id uuid; changed_count integer;
begin
  if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
  if target_capabilities is null or jsonb_typeof(target_capabilities)<>'array' or jsonb_array_length(target_capabilities)>200 then raise exception 'invalid capability snapshot'; end if;
  select workspace_id into target_workspace_id from public.engine_connections where id=target_connection_id and status<>'revoked' for update;
  if target_workspace_id is null then raise exception 'engine connection is unavailable'; end if;
  delete from public.engine_capabilities where connection_id=target_connection_id;
  insert into public.engine_capabilities(workspace_id,connection_id,operation_key,display_name,description,pipeline_stage,available,runtime,input_schema)
    select target_workspace_id,target_connection_id,entry->>'operation_key',entry->>'display_name',coalesce(entry->>'description',''),
      coalesce(entry->>'pipeline_stage','workspace'),true,'mcp',coalesce(entry->'input_schema','{}'::jsonb)
    from jsonb_array_elements(target_capabilities) as entry;
  get diagnostics changed_count=ROW_COUNT;
  update public.engine_connections set status='connected',last_seen_at=now(),capabilities_updated_at=now(),updated_at=now()
    where id=target_connection_id;
  return changed_count;
end; $$;

create function public.mark_studio_engine_offline(target_connection_id uuid)
returns boolean language plpgsql security definer set search_path=''
as $$
declare changed integer;
begin
  if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
  update public.engine_connections set status='offline',last_seen_at=null,updated_at=now()
    where id=target_connection_id and status<>'revoked';
  get diagnostics changed=row_count;
  return changed=1;
end; $$;

create function public.handle_studio_engine_token_revocation() returns trigger
language plpgsql security definer set search_path=''
as $$
begin
  if old.revoked_at is null and new.revoked_at is not null then
    update public.engine_connections set status='revoked',updated_at=now()
      where mcp_token_id=new.id;
    delete from public.engine_secrets where connection_id in
      (select id from public.engine_connections where mcp_token_id=new.id);
  end if;
  return new;
end; $$;
create trigger studio_engine_token_revoked after update of revoked_at on public.workspace_mcp_tokens
  for each row execute function public.handle_studio_engine_token_revocation();

revoke all on function public.store_studio_engine_connection(uuid,text,text,uuid,bytea,timestamptz,bytea,text),
  public.sync_studio_engine_capabilities(uuid,jsonb),public.mark_studio_engine_offline(uuid) from public,authenticated,anon;
grant execute on function public.store_studio_engine_connection(uuid,text,text,uuid,bytea,timestamptz,bytea,text),
  public.sync_studio_engine_capabilities(uuid,jsonb),public.mark_studio_engine_offline(uuid) to service_role;
