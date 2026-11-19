-- Hosted Studio control-plane foundation. Apply only to a dedicated Supabase project.
create extension if not exists pgcrypto;

create table public.workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null check (length(trim(name)) between 1 and 120),
  slug text not null unique check (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table public.workspace_members (
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('owner','admin','producer','reviewer')),
  joined_at timestamptz not null default now(), primary key(workspace_id,user_id)
);
create index workspace_members_user_idx on public.workspace_members(user_id,workspace_id);
create table public.workspace_mcp_tokens (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  label text not null check(length(trim(label)) between 1 and 120),
  token_hash bytea not null unique check(octet_length(token_hash)=32),
  scopes text[] not null default array['mcp:read','mcp:write'] check(scopes <@ array['mcp:read','mcp:write']),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(), expires_at timestamptz not null,
  revoked_at timestamptz, last_used_at timestamptz,
  check(expires_at>created_at)
);
create index workspace_mcp_tokens_workspace_idx on public.workspace_mcp_tokens(workspace_id,created_at desc);
create table public.projects (
  id uuid primary key default gen_random_uuid(), workspace_id uuid not null references public.workspaces(id) on delete cascade,
  title text not null check(length(trim(title)) between 1 and 240),
  platform text not null default 'youtube' check(platform in ('youtube','instagram','multi')),
  format text not null default 'vertical' check(format in ('vertical','landscape','square')),
  status text not null default 'brief' check(status in ('brief','research','in_progress','review','complete','archived')),
  brief jsonb not null default '{}'::jsonb, created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(), unique(workspace_id,id)
);
create index projects_workspace_updated_idx on public.projects(workspace_id,updated_at desc);

-- A creator can connect one or more self-hosted or hosted MCP engines. The
-- endpoint credential is encrypted outside the browser; tool metadata is a
-- safe capability snapshot the Studio can display before a job is proposed.
create table public.engine_connections (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  label text not null check(length(trim(label)) between 1 and 120),
  status text not null default 'pending' check(status in ('pending','connected','offline','revoked')),
  last_seen_at timestamptz,
  capabilities_updated_at timestamptz,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique(workspace_id,id)
);
create table public.engine_secrets (
  connection_id uuid primary key, workspace_id uuid not null,
  ciphertext bytea not null, key_version text not null, updated_at timestamptz not null default now(),
  foreign key(workspace_id,connection_id) references public.engine_connections(workspace_id,id) on delete cascade
);
create table public.engine_capabilities (
  id uuid primary key default gen_random_uuid(), workspace_id uuid not null,
  connection_id uuid not null, operation_key text not null, display_name text not null,
  description text not null default '', pipeline_stage text not null,
  available boolean not null default true, runtime text not null default 'unknown',
  estimated_cost_usd numeric(12,6), input_schema jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  foreign key(workspace_id,connection_id) references public.engine_connections(workspace_id,id) on delete cascade,
  unique(workspace_id,id), unique(workspace_id,connection_id,id),
  unique(workspace_id,connection_id,operation_key)
);
create index engine_capabilities_workspace_idx on public.engine_capabilities(workspace_id,available,pipeline_stage);

create table public.jobs (
  id uuid primary key default gen_random_uuid(), workspace_id uuid not null, project_id uuid not null,
  engine_connection_id uuid, engine_capability_id uuid,
  operation text not null check(length(operation) between 1 and 120),
  status text not null default 'queued' check(status in ('queued','running','waiting_approval','succeeded','failed','cancelled','reconciling')),
  progress smallint not null default 0 check(progress between 0 and 100),
  progress_label text not null default '' check(length(progress_label)<=160), idempotency_key text,
  input jsonb not null default '{}'::jsonb, result jsonb, error jsonb, attempt integer not null default 0 check(attempt>=0),
  lease_owner text, lease_expires_at timestamptz, started_at timestamptz, finished_at timestamptz,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  foreign key(workspace_id,project_id) references public.projects(workspace_id,id) on delete cascade,
  foreign key(workspace_id,engine_connection_id,engine_capability_id)
    references public.engine_capabilities(workspace_id,connection_id,id),
  unique(workspace_id,id), unique(workspace_id,idempotency_key)
);
create index jobs_worker_queue_idx on public.jobs(status,created_at) where status in ('queued','reconciling');
create index jobs_workspace_recent_idx on public.jobs(workspace_id,created_at desc);

-- Hosted workers claim jobs with row-level locking so multiple workers cannot
-- start the same job. Expired work is moved to reconciliation, never retried
-- automatically after an uncertain provider outcome.
create function public.claim_studio_job(worker_name text,lease_seconds integer default 300)
returns setof public.jobs language plpgsql security definer set search_path=''
as $$
begin
 if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
 if worker_name is null or length(trim(worker_name)) not between 1 and 120 then raise exception 'invalid worker name'; end if;
 if lease_seconds not between 30 and 1800 then raise exception 'lease must be between 30 and 1800 seconds'; end if;
 return query
 with next_job as (
   select j.id from public.jobs j where j.status='queued'
   order by j.created_at for update skip locked limit 1
 )
 update public.jobs j set status='running',lease_owner=worker_name,
   lease_expires_at=now()+make_interval(secs=>lease_seconds),
   started_at=coalesce(j.started_at,now()),attempt=j.attempt+1,updated_at=now()
 from next_job n where j.id=n.id returning j.*;
end; $$;

create function public.heartbeat_studio_job(target_job_id uuid,worker_name text,lease_seconds integer default 300)
returns boolean language plpgsql security definer set search_path=''
as $$
declare changed integer;
begin
 if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
 if lease_seconds not between 30 and 1800 then raise exception 'lease must be between 30 and 1800 seconds'; end if;
 update public.jobs set lease_expires_at=now()+make_interval(secs=>lease_seconds),updated_at=now()
 where id=target_job_id and status='running' and lease_owner=worker_name and lease_expires_at>now();
 get diagnostics changed=row_count;
 return changed=1;
end; $$;

create function public.report_studio_job_progress(target_job_id uuid,worker_name text,progress_value smallint,stage_label text default '')
returns boolean language plpgsql security definer set search_path=''
as $$
declare changed integer;
begin
 if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
 if progress_value not between 0 and 99 then raise exception 'progress must be between 0 and 99'; end if;
 if length(coalesce(stage_label,''))>160 then raise exception 'progress label is too long'; end if;
 update public.jobs set progress=greatest(progress,progress_value),
   progress_label=coalesce(stage_label,''),updated_at=now()
 where id=target_job_id and status='running' and lease_owner=worker_name and lease_expires_at>now();
 get diagnostics changed=row_count;
 return changed=1;
end; $$;

create function public.finish_studio_job(target_job_id uuid,worker_name text,succeeded boolean,job_result jsonb default null,job_error jsonb default null)
returns boolean language plpgsql security definer set search_path=''
as $$
declare changed integer;
begin
 if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
 if succeeded and job_error is not null then raise exception 'successful job cannot include an error'; end if;
 if not succeeded and job_error is null then raise exception 'failed job requires an error detail'; end if;
 update public.jobs set status=case when succeeded then 'succeeded' else 'failed' end,
   progress=case when succeeded then 100 else progress end,result=job_result,error=job_error,
   finished_at=now(),lease_owner=null,lease_expires_at=null,updated_at=now()
 where id=target_job_id and status='running' and lease_owner=worker_name and lease_expires_at>now();
 get diagnostics changed=row_count;
 return changed=1;
end; $$;

create function public.reconcile_expired_studio_jobs()
returns integer language plpgsql security definer set search_path=''
as $$
declare changed integer;
begin
 if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
 update public.jobs set status='reconciling',lease_owner=null,lease_expires_at=null,updated_at=now(),
   error=coalesce(error,'{}'::jsonb)||jsonb_build_object('reason','worker_lease_expired','automatic_retry',false)
 where status='running' and lease_expires_at<=now();
 get diagnostics changed=row_count;
 return changed;
end; $$;
revoke all on function public.claim_studio_job(text,integer),public.heartbeat_studio_job(uuid,text,integer),
  public.report_studio_job_progress(uuid,text,smallint,text),public.finish_studio_job(uuid,text,boolean,jsonb,jsonb),
  public.reconcile_expired_studio_jobs() from public,authenticated,anon;
grant execute on function public.claim_studio_job(text,integer),public.heartbeat_studio_job(uuid,text,integer),
  public.report_studio_job_progress(uuid,text,smallint,text),public.finish_studio_job(uuid,text,boolean,jsonb,jsonb),
  public.reconcile_expired_studio_jobs() to service_role;
-- The browser can see connection metadata, never credential ciphertext.
create table public.provider_connections (
  id uuid primary key default gen_random_uuid(), workspace_id uuid not null references public.workspaces(id) on delete cascade,
  provider text not null, label text not null, credential_hint text,
  status text not null default 'connected' check(status in ('connected','needs_attention','revoked')),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique(workspace_id,id)
);
create unique index provider_connections_active_label_idx on public.provider_connections(workspace_id,provider,label) where status<>'revoked';
create table public.provider_secrets (
  connection_id uuid primary key, workspace_id uuid not null, ciphertext bytea not null, key_version text not null,
  updated_at timestamptz not null default now(),
  foreign key(workspace_id,connection_id) references public.provider_connections(workspace_id,id) on delete cascade
);
create table public.audit_events (
  id bigint generated always as identity primary key, workspace_id uuid not null references public.workspaces(id) on delete cascade,
  actor_id uuid references auth.users(id) on delete set null, action text not null, subject_type text not null,
  subject_id text, metadata jsonb not null default '{}'::jsonb, created_at timestamptz not null default now()
);
create index audit_events_workspace_recent_idx on public.audit_events(workspace_id,created_at desc);
create function public.create_workspace_mcp_token(
  target_workspace_id uuid,target_label text,presented_hash bytea,token_scopes text[],target_expires_at timestamptz,actor_id uuid
) returns uuid language plpgsql security definer set search_path=''
as $$
declare new_token_id uuid;
begin
 if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
 if not exists(select 1 from public.workspace_members m where m.workspace_id=target_workspace_id and m.user_id=actor_id and m.role in ('owner','admin')) then
   raise exception 'workspace owner or admin required' using errcode='42501';
 end if;
 if length(trim(target_label)) not between 1 and 120 then raise exception 'invalid token label'; end if;
 if octet_length(presented_hash)<>32 then raise exception 'invalid token hash'; end if;
 if token_scopes is null or cardinality(token_scopes)=0 or not (token_scopes <@ array['mcp:read','mcp:write']) then raise exception 'invalid token scopes'; end if;
 if target_expires_at<=now() or target_expires_at>now()+interval '366 days' then raise exception 'token expiry must be within 366 days'; end if;
 insert into public.workspace_mcp_tokens(workspace_id,label,token_hash,scopes,created_by,expires_at)
   values(target_workspace_id,trim(target_label),presented_hash,token_scopes,actor_id,target_expires_at) returning id into new_token_id;
 insert into public.audit_events(workspace_id,actor_id,action,subject_type,subject_id,metadata)
   values(target_workspace_id,actor_id,'workspace.mcp_token.created','workspace_mcp_token',new_token_id::text,
     jsonb_build_object('label',trim(target_label),'scopes',token_scopes,'expires_at',target_expires_at));
 return new_token_id;
end; $$;
create function public.resolve_workspace_mcp_token(presented_hash bytea)
returns table(token_id uuid,workspace_id uuid,subject_id uuid,scopes text[],member_role text)
language plpgsql security definer set search_path=''
as $$
begin
 if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
 return query
 update public.workspace_mcp_tokens t set last_used_at=now()
   where t.token_hash=presented_hash and t.revoked_at is null and t.expires_at>now()
   and exists(select 1 from public.workspace_members m where m.workspace_id=t.workspace_id and m.user_id=t.created_by and m.role in ('owner','admin','producer'))
   returning t.id,t.workspace_id,t.created_by,t.scopes,
     (select m.role from public.workspace_members m where m.workspace_id=t.workspace_id and m.user_id=t.created_by);
end; $$;
create function public.revoke_workspace_mcp_token(target_workspace_id uuid,target_token_id uuid,actor_id uuid)
returns boolean language plpgsql security definer set search_path=''
as $$
declare token_label text; changed integer;
begin
 if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
 if not exists(select 1 from public.workspace_members m where m.workspace_id=target_workspace_id and m.user_id=actor_id and m.role in ('owner','admin')) then
   raise exception 'workspace owner or admin required' using errcode='42501';
 end if;
 update public.workspace_mcp_tokens set revoked_at=now()
   where id=target_token_id and workspace_id=target_workspace_id and revoked_at is null returning label into token_label;
 get diagnostics changed=row_count;
 if changed=1 then
   insert into public.audit_events(workspace_id,actor_id,action,subject_type,subject_id,metadata)
     values(target_workspace_id,actor_id,'workspace.mcp_token.revoked','workspace_mcp_token',target_token_id::text,jsonb_build_object('label',token_label));
 end if;
 return changed=1;
end; $$;
create function public.authorize_workspace_project(target_workspace_id uuid,target_project_id uuid)
returns boolean language sql stable security definer set search_path=''
as $$ select exists(select 1 from public.projects p where p.workspace_id=target_workspace_id and p.id=target_project_id); $$;
revoke all on function public.create_workspace_mcp_token(uuid,text,bytea,text[],timestamptz,uuid),
  public.resolve_workspace_mcp_token(bytea),public.revoke_workspace_mcp_token(uuid,uuid,uuid),
  public.authorize_workspace_project(uuid,uuid) from public,authenticated,anon;
grant execute on function public.create_workspace_mcp_token(uuid,text,bytea,text[],timestamptz,uuid),
  public.resolve_workspace_mcp_token(bytea),public.revoke_workspace_mcp_token(uuid,uuid,uuid),
  public.authorize_workspace_project(uuid,uuid) to service_role;
-- A provider credential and its safe display metadata must commit together.
-- The service-role-only RPC is called only by the authenticated Studio server
-- after it has checked that the actor is a workspace owner or admin.
create function public.store_provider_credential(
  target_workspace_id uuid, target_provider text, target_label text,
  safe_hint text, actor_id uuid, encrypted_payload bytea, encryption_version text
) returns uuid language plpgsql security definer set search_path=''
as $$
declare connection_id uuid;
begin
 if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
 if target_provider !~ '^[a-z][a-z0-9_-]{1,63}$' then raise exception 'invalid provider id'; end if;
 if length(trim(target_label)) not between 1 and 120 then raise exception 'invalid connection label'; end if;
 if encrypted_payload is null or octet_length(encrypted_payload)<29 then raise exception 'invalid encrypted credential'; end if;
 if encryption_version <> 'aes-256-gcm-v1' then raise exception 'unsupported encryption version'; end if;
 if safe_hint !~ '^••••[A-Za-z0-9_-]{4}$' then raise exception 'invalid credential hint'; end if;
 if not exists(select 1 from public.workspace_members m where m.workspace_id=target_workspace_id and m.user_id=actor_id and m.role in ('owner','admin')) then
   raise exception 'workspace owner or admin required' using errcode='42501';
 end if;
 insert into public.provider_connections(workspace_id,provider,label,credential_hint,status,created_by)
   values(target_workspace_id,target_provider,trim(target_label),safe_hint,'connected',actor_id)
   returning id into connection_id;
 insert into public.provider_secrets(workspace_id,connection_id,ciphertext,key_version)
   values(target_workspace_id,connection_id,encrypted_payload,encryption_version);
 insert into public.audit_events(workspace_id,actor_id,action,subject_type,subject_id,metadata)
   values(target_workspace_id,actor_id,'provider.credential.added','provider_connection',connection_id::text,
     jsonb_build_object('provider',target_provider,'label',trim(target_label)));
 return connection_id;
end; $$;
revoke all on function public.store_provider_credential(uuid,text,text,text,uuid,bytea,text) from public,authenticated,anon;
grant execute on function public.store_provider_credential(uuid,text,text,text,uuid,bytea,text) to service_role;
create function public.revoke_provider_credential(target_workspace_id uuid,target_connection_id uuid,actor_id uuid)
returns boolean language plpgsql security definer set search_path=''
as $$
declare changed integer; safe_metadata jsonb;
begin
 if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
 if not exists(select 1 from public.workspace_members m where m.workspace_id=target_workspace_id and m.user_id=actor_id and m.role in ('owner','admin')) then
   raise exception 'workspace owner or admin required' using errcode='42501';
 end if;
 select jsonb_build_object('provider',provider,'label',label) into safe_metadata
   from public.provider_connections where workspace_id=target_workspace_id and id=target_connection_id and status<>'revoked';
 if safe_metadata is null then return false; end if;
 delete from public.provider_secrets where workspace_id=target_workspace_id and connection_id=target_connection_id;
 update public.provider_connections set status='revoked',updated_at=now()
   where workspace_id=target_workspace_id and id=target_connection_id and status<>'revoked';
 get diagnostics changed=row_count;
 if changed=1 then
   insert into public.audit_events(workspace_id,actor_id,action,subject_type,subject_id,metadata)
     values(target_workspace_id,actor_id,'provider.credential.revoked','provider_connection',target_connection_id::text,safe_metadata);
 end if;
 return changed=1;
end; $$;
revoke all on function public.revoke_provider_credential(uuid,uuid,uuid) from public,authenticated,anon;
grant execute on function public.revoke_provider_credential(uuid,uuid,uuid) to service_role;
create table public.usage_events (
  id uuid primary key default gen_random_uuid(), workspace_id uuid not null references public.workspaces(id) on delete restrict,
  project_id uuid, job_id uuid, event_type text not null check(event_type in ('reservation','actual','release','refund','adjustment')),
  provider text, operation text not null, quantity numeric(18,6) not null default 0 check(quantity>=0), amount numeric(18,6) not null default 0 check(amount>=0),
  currency char(3) not null default 'USD' check(currency ~ '^[A-Z]{3}$'),
  idempotency_key text not null check(length(idempotency_key) between 1 and 200),
  metadata jsonb not null default '{}'::jsonb, created_at timestamptz not null default now(),
  foreign key(workspace_id,project_id) references public.projects(workspace_id,id),
  foreign key(workspace_id,job_id) references public.jobs(workspace_id,id),
  unique(workspace_id,idempotency_key)
);
create index usage_events_workspace_recent_idx on public.usage_events(workspace_id,created_at desc);
create table public.entitlements (
  workspace_id uuid primary key references public.workspaces(id) on delete cascade,
  plan text not null default 'pilot', status text not null default 'active' check(status in ('trialing','active','past_due','cancelled','paused')),
  seats integer not null default 3 check(seats>0), monthly_job_limit integer not null default 30 check(monthly_job_limit>=0),
  billing_provider text not null default 'manual', provider_customer_id text, provider_subscription_id text,
  current_period_start timestamptz, current_period_end timestamptz, updated_at timestamptz not null default now()
);
-- Append-only ledgers: fixes and reversals are new events, never row rewrites.
create function public.reject_ledger_mutation() returns trigger
language plpgsql set search_path=''
as $$ begin raise exception '% is append-only; insert a compensating event instead',tg_table_name; end; $$;
create trigger usage_events_append_only before update or delete on public.usage_events
  for each row execute function public.reject_ledger_mutation();
create trigger audit_events_append_only before update or delete on public.audit_events
  for each row execute function public.reject_ledger_mutation();

create function public.is_workspace_member(target_workspace_id uuid) returns boolean
language sql stable security definer set search_path=''
as $$ select exists(select 1 from public.workspace_members m where m.workspace_id=target_workspace_id and m.user_id=(select auth.uid())); $$;
create function public.has_workspace_role(target_workspace_id uuid, allowed_roles text[]) returns boolean
language sql stable security definer set search_path=''
as $$ select exists(select 1 from public.workspace_members m where m.workspace_id=target_workspace_id and m.user_id=(select auth.uid()) and m.role=any(allowed_roles)); $$;
revoke all on function public.is_workspace_member(uuid) from public;
revoke all on function public.has_workspace_role(uuid,text[]) from public;
grant execute on function public.is_workspace_member(uuid),public.has_workspace_role(uuid,text[]) to authenticated,service_role;

create function public.create_workspace(workspace_name text,workspace_slug text) returns uuid
language plpgsql security definer set search_path=''
as $$
declare wid uuid; clean_name text:=trim(workspace_name); clean_slug text:=lower(trim(workspace_slug));
begin
 if auth.uid() is null then raise exception 'authentication required' using errcode='42501'; end if;
 if clean_name is null or length(clean_name) not between 1 and 120 then raise exception 'invalid workspace name'; end if;
 if clean_slug is null or clean_slug !~ '^[a-z0-9]+(-[a-z0-9]+)*$' then raise exception 'invalid workspace slug'; end if;
 insert into public.workspaces(name,slug,created_by) values(clean_name,clean_slug,auth.uid()) returning id into wid;
 insert into public.workspace_members(workspace_id,user_id,role) values(wid,auth.uid(),'owner');
 insert into public.entitlements(workspace_id) values(wid);
 insert into public.audit_events(workspace_id,actor_id,action,subject_type,subject_id) values(wid,auth.uid(),'workspace.created','workspace',wid::text);
 return wid;
end; $$;
revoke all on function public.create_workspace(text,text) from public;
grant execute on function public.create_workspace(text,text) to authenticated;

alter table public.workspaces enable row level security;
alter table public.workspace_members enable row level security;
alter table public.workspace_mcp_tokens enable row level security;
alter table public.projects enable row level security;
alter table public.jobs enable row level security;
alter table public.engine_connections enable row level security;
alter table public.engine_secrets enable row level security;
alter table public.engine_capabilities enable row level security;
alter table public.provider_connections enable row level security;
alter table public.provider_secrets enable row level security;
alter table public.usage_events enable row level security;
alter table public.entitlements enable row level security;
alter table public.audit_events enable row level security;
create policy workspace_read on public.workspaces for select to authenticated using(public.is_workspace_member(id));
create policy workspace_update on public.workspaces for update to authenticated using(public.has_workspace_role(id,array['owner','admin'])) with check(public.has_workspace_role(id,array['owner','admin']));
create policy membership_read on public.workspace_members for select to authenticated using(public.is_workspace_member(workspace_id));
create policy membership_admin on public.workspace_members for all to authenticated using(public.has_workspace_role(workspace_id,array['owner','admin'])) with check(public.has_workspace_role(workspace_id,array['owner','admin']));
create policy projects_read on public.projects for select to authenticated using(public.is_workspace_member(workspace_id));
create policy projects_create on public.projects for insert to authenticated with check(public.has_workspace_role(workspace_id,array['owner','admin','producer']) and created_by=(select auth.uid()));
create policy projects_update on public.projects for update to authenticated using(public.has_workspace_role(workspace_id,array['owner','admin','producer'])) with check(public.has_workspace_role(workspace_id,array['owner','admin','producer']));
-- Projects are archived rather than deleted so the immutable usage ledger keeps its references.
create policy jobs_read on public.jobs for select to authenticated using(public.is_workspace_member(workspace_id));
-- No authenticated job writes: enqueue and transitions must pass server-side approval, idempotency and cost checks.
create policy engine_connections_read on public.engine_connections for select to authenticated using(public.is_workspace_member(workspace_id));
create policy engine_capabilities_read on public.engine_capabilities for select to authenticated using(public.is_workspace_member(workspace_id));
-- Engine credentials and capability mutations are worker/service-only.
create policy provider_connections_read on public.provider_connections for select to authenticated using(public.is_workspace_member(workspace_id));
-- provider_secrets, usage_events, entitlements and audit_events have no authenticated write policies.
create policy usage_read on public.usage_events for select to authenticated using(public.is_workspace_member(workspace_id));
create policy entitlements_admin_read on public.entitlements for select to authenticated using(public.has_workspace_role(workspace_id,array['owner','admin']));
create policy audit_admin_read on public.audit_events for select to authenticated using(public.has_workspace_role(workspace_id,array['owner','admin']));
grant select,update on public.workspaces to authenticated;
grant select,insert,update,delete on public.workspace_members to authenticated;
-- Token hashes are service-only and are never selected by Studio browser sessions.
grant select on public.provider_connections to authenticated;
grant select,insert,update on public.projects to authenticated;
grant select on public.jobs,public.engine_connections,public.engine_capabilities,public.usage_events,public.entitlements,public.audit_events to authenticated;
grant all on public.workspaces,public.workspace_members,public.workspace_mcp_tokens,public.projects,public.jobs,public.engine_connections,public.engine_secrets,public.engine_capabilities,public.provider_connections,public.provider_secrets,public.usage_events,public.entitlements,public.audit_events to service_role;

create function public.can_access_studio_project(target_workspace_id uuid,target_project_id uuid) returns boolean
language sql stable security definer set search_path=''
as $$ select public.is_workspace_member(target_workspace_id) and exists(select 1 from public.projects p where p.workspace_id=target_workspace_id and p.id=target_project_id); $$;
revoke all on function public.can_access_studio_project(uuid,uuid) from public;
grant execute on function public.can_access_studio_project(uuid,uuid) to authenticated,service_role;

create function public.prevent_workspace_transfer() returns trigger
language plpgsql set search_path=''
as $$ begin
 if new.workspace_id is distinct from old.workspace_id then
   raise exception 'workspace ownership cannot be transferred';
 end if;
 return new;
end; $$;
create trigger projects_workspace_immutable before update on public.projects
  for each row execute function public.prevent_workspace_transfer();
create trigger connections_workspace_immutable before update on public.provider_connections
  for each row execute function public.prevent_workspace_transfer();
create trigger engine_workspace_immutable before update on public.engine_connections
  for each row execute function public.prevent_workspace_transfer();
create trigger capability_workspace_immutable before update on public.engine_capabilities
  for each row execute function public.prevent_workspace_transfer();
create trigger membership_workspace_immutable before update on public.workspace_members
  for each row execute function public.prevent_workspace_transfer();

create function public.prevent_last_workspace_owner() returns trigger
language plpgsql set search_path=''
as $$
declare owner_count integer;
begin
 if old.role='owner' and (tg_op='DELETE' or new.role is distinct from 'owner' or new.user_id is distinct from old.user_id) then
   -- Serialize owner removals against one another before counting.
   perform 1 from public.workspaces w where w.id=old.workspace_id for update;
   select count(*) into owner_count from public.workspace_members m
     where m.workspace_id=old.workspace_id and m.role='owner' and m.user_id<>old.user_id;
   if owner_count=0 then raise exception 'a workspace must retain at least one owner'; end if;
 end if;
 if tg_op='DELETE' then return old; end if;
 return new;
end; $$;
create trigger workspace_owner_required before delete or update on public.workspace_members
  for each row execute function public.prevent_last_workspace_owner();

insert into storage.buckets(id,name,public,file_size_limit) values('studio-private','studio-private',false,1073741824)
on conflict(id) do update set public=false;
create policy studio_media_read on storage.objects for select to authenticated using(bucket_id='studio-private' and public.can_access_studio_project((storage.foldername(name))[1]::uuid,(storage.foldername(name))[2]::uuid));
create policy studio_media_upload on storage.objects for insert to authenticated with check(bucket_id='studio-private' and public.has_workspace_role((storage.foldername(name))[1]::uuid,array['owner','admin','producer']) and public.can_access_studio_project((storage.foldername(name))[1]::uuid,(storage.foldername(name))[2]::uuid));
create policy studio_media_update on storage.objects for update to authenticated using(bucket_id='studio-private' and public.has_workspace_role((storage.foldername(name))[1]::uuid,array['owner','admin','producer']) and public.can_access_studio_project((storage.foldername(name))[1]::uuid,(storage.foldername(name))[2]::uuid)) with check(bucket_id='studio-private' and public.has_workspace_role((storage.foldername(name))[1]::uuid,array['owner','admin','producer']) and public.can_access_studio_project((storage.foldername(name))[1]::uuid,(storage.foldername(name))[2]::uuid));
create policy studio_media_delete on storage.objects for delete to authenticated using(bucket_id='studio-private' and public.has_workspace_role((storage.foldername(name))[1]::uuid,array['owner','admin']) and public.can_access_studio_project((storage.foldername(name))[1]::uuid,(storage.foldername(name))[2]::uuid));
