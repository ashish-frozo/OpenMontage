-- Mirror each canonical MCP checkpoint into the Studio workspace dashboard.
alter table public.projects
  add column if not exists current_stage text,
  add column if not exists current_checkpoint_status text,
  add column if not exists approval_needed boolean not null default false,
  add column if not exists stage_updated_at timestamptz;

alter table public.projects
  drop constraint if exists projects_current_checkpoint_status_check;
alter table public.projects
  add constraint projects_current_checkpoint_status_check
  check (current_checkpoint_status is null or current_checkpoint_status in
    ('in_progress','awaiting_human','completed','failed'));

create or replace function public.sync_studio_project_progress(
  target_workspace_id uuid,
  target_project_id uuid,
  target_stage text,
  target_checkpoint_status text,
  target_approval_needed boolean,
  target_project_status text
) returns boolean
language plpgsql security definer set search_path=''
as $$
declare changed integer;
begin
  if auth.role() <> 'service_role' then
    raise exception 'service role required' using errcode='42501';
  end if;
  if target_stage is null or target_stage !~ '^[a-z0-9][a-z0-9_-]{0,63}$' then
    raise exception 'invalid pipeline stage';
  end if;
  if target_checkpoint_status is null or target_checkpoint_status not in ('in_progress','awaiting_human','completed','failed') then
    raise exception 'invalid checkpoint status';
  end if;
  if target_approval_needed is null then
    raise exception 'approval state is required';
  end if;
  if target_approval_needed and target_checkpoint_status <> 'awaiting_human' then
    raise exception 'approval can only be pending for an awaiting-human checkpoint';
  end if;
  if target_project_status is null or target_project_status not in ('research','in_progress','review','complete') then
    raise exception 'invalid mirrored project status';
  end if;
  update public.projects
    set current_stage=target_stage,
        current_checkpoint_status=target_checkpoint_status,
        approval_needed=target_approval_needed,
        status=target_project_status,
        stage_updated_at=now(),
        updated_at=now()
    where workspace_id=target_workspace_id and id=target_project_id;
  get diagnostics changed=row_count;
  return changed=1;
end; $$;

revoke all on function public.sync_studio_project_progress(uuid,uuid,text,text,boolean,text)
  from public, anon, authenticated;
grant execute on function public.sync_studio_project_progress(uuid,uuid,text,text,boolean,text)
  to service_role;

comment on function public.sync_studio_project_progress(uuid,uuid,text,text,boolean,text) is
  'Mirror a validated MCP checkpoint into the matching workspace project for Studio display.';
