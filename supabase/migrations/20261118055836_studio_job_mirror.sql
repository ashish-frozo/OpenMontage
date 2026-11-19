-- Mirror lifecycle state from the persistent, workspace-local Factory queue
-- into Studio. This function never claims or executes work.
create function public.sync_hosted_job_statuses(target_workspace_id uuid, job_records jsonb)
returns integer
language plpgsql
security invoker
set search_path=''
as $$
declare
  synced integer;
  record_count integer;
begin
  if current_user <> 'service_role' then
    raise exception 'service role required' using errcode='42501';
  end if;
  if target_workspace_id is null or job_records is null or jsonb_typeof(job_records) <> 'array' then
    raise exception 'workspace and a job array are required';
  end if;
  record_count := jsonb_array_length(job_records);
  if record_count > 500 then raise exception 'at most 500 jobs per sync'; end if;

  if exists (
    select 1
    from jsonb_to_recordset(job_records) as j(
      job_id text, project_id uuid, operation text, status text,
      progress integer, progress_label text
    )
    left join public.projects p
      on p.id=j.project_id and p.workspace_id=target_workspace_id
    where p.id is null
       or j.job_id is null
       or j.job_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
       or j.operation is null or length(j.operation) not between 1 and 120
       or j.status is null or j.status not in ('queued','running','succeeded','failed','cancelled','reconciling')
       or j.progress is null or j.progress not between 0 and 100
       or length(coalesce(j.progress_label,'')) > 160
  ) then raise exception 'invalid or foreign job record'; end if;

  if exists (
    select 1 from jsonb_to_recordset(job_records) as j(job_id text)
    group by j.job_id having count(*) > 1
  ) then raise exception 'duplicate job id in sync batch'; end if;

  insert into public.jobs (
    id, workspace_id, project_id, operation, status, progress, progress_label,
    created_by, started_at, finished_at, updated_at
  )
  select j.job_id::uuid, target_workspace_id, j.project_id, j.operation, j.status,
         j.progress, coalesce(j.progress_label,''), p.created_by,
         case when j.status <> 'queued' then now() else null end,
         case when j.status in ('succeeded','failed','cancelled') then now() else null end,
         now()
  from jsonb_to_recordset(job_records) as j(
    job_id text, project_id uuid, operation text, status text,
    progress integer, progress_label text
  )
  join public.projects p on p.id=j.project_id and p.workspace_id=target_workspace_id
  on conflict (id) do update set
    status=excluded.status,
    progress=greatest(public.jobs.progress,excluded.progress),
    progress_label=excluded.progress_label,
    started_at=coalesce(public.jobs.started_at,excluded.started_at),
    finished_at=case
      when excluded.status in ('succeeded','failed','cancelled') then coalesce(public.jobs.finished_at,now())
      else public.jobs.finished_at
    end,
    updated_at=now()
  where public.jobs.workspace_id=excluded.workspace_id
    and public.jobs.project_id=excluded.project_id
    and public.jobs.operation=excluded.operation
    and public.jobs.created_by=excluded.created_by;

  get diagnostics synced = row_count;
  if synced <> record_count then raise exception 'job sync identity conflict'; end if;
  return synced;
end; $$;
revoke all on function public.sync_hosted_job_statuses(uuid,jsonb) from public,authenticated,anon;
grant execute on function public.sync_hosted_job_statuses(uuid,jsonb) to service_role;
