-- Hosted MCP submissions become durable, lease-claimed Supabase jobs.
-- The local SQLite runner remains the execution adapter and self-hosted path;
-- hosted job lifecycle, retry safety, limits, and usage reservations live here.

alter table public.jobs drop constraint if exists jobs_status_check;
alter table public.jobs add constraint jobs_status_check
  check(status in ('queued','running','cancelling','waiting_approval','succeeded','failed','cancelled','reconciling'));

create or replace function public.enqueue_studio_job(
  target_workspace_id uuid,
  target_project_id uuid,
  target_operation text,
  target_idempotency_key text,
  target_created_by uuid,
  target_input jsonb,
  target_estimated_cost numeric,
  target_provider text default null
) returns setof public.jobs
language plpgsql security definer set search_path=''
as $$
declare
  v_existing public.jobs%rowtype;
  v_job public.jobs%rowtype;
  v_role text;
  v_plan text;
  v_monthly_limit integer;
  v_period_start timestamptz;
  v_job_count integer;
  v_max_concurrent integer;
  v_limit numeric;
  v_committed numeric;
begin
  if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
  if target_operation is null or length(trim(target_operation)) not between 1 and 120 then raise exception 'invalid operation'; end if;
  if target_idempotency_key is null or length(target_idempotency_key) not between 1 and 200 then raise exception 'invalid idempotency key'; end if;
  if target_input is null or jsonb_typeof(target_input) <> 'object' or pg_column_size(target_input) > 65536 then raise exception 'invalid or oversized job input'; end if;
  if target_estimated_cost is null or target_estimated_cost < 0 or target_estimated_cost::text in ('NaN','Infinity','-Infinity') then raise exception 'invalid cost estimate'; end if;
  if coalesce(target_input->>'plan_id','') !~ '^[0-9a-f]{32}$'
    or coalesce(target_input->>'step_id','') !~ '^[0-9a-f]{32}$' then raise exception 'invalid route step identity'; end if;
  if coalesce(target_input->>'estimated_cost_usd','') !~ '^[0-9]+(\.[0-9]+)?$'
    or (target_input->>'estimated_cost_usd')::numeric <> target_estimated_cost then raise exception 'job estimate mismatch'; end if;
  if jsonb_typeof(coalesce(target_input->'depends_on','[]'::jsonb)) <> 'array'
    or jsonb_array_length(coalesce(target_input->'depends_on','[]'::jsonb)) > 128 then raise exception 'invalid job dependencies'; end if;
  if target_created_by is null or not exists(
    select 1 from public.workspace_members m where m.workspace_id=target_workspace_id
      and m.user_id=target_created_by and m.role in ('owner','admin','producer')
  ) then raise exception 'producer membership required' using errcode='42501'; end if;

  -- Serialize budget and idempotency checks per project.
  perform 1 from public.projects p where p.workspace_id=target_workspace_id and p.id=target_project_id for update;
  if not found then raise exception 'project is not available in this workspace' using errcode='42501'; end if;

  select * into v_existing from public.jobs j
    where j.workspace_id=target_workspace_id and j.idempotency_key=target_idempotency_key for update;
  if found then
    if v_existing.project_id <> target_project_id or v_existing.operation <> target_operation
      or v_existing.input <> target_input then raise exception 'idempotency key already used for different work'; end if;
    return next v_existing;
    return;
  end if;

  -- A new key cannot duplicate the same active, successful, or uncertain work.
  if target_input ? 'fingerprint' then
    select * into v_existing from public.jobs j
      where j.workspace_id=target_workspace_id and j.project_id=target_project_id
        and j.input->>'fingerprint'=target_input->>'fingerprint'
        and j.status in ('queued','running','cancelling','succeeded','reconciling')
      order by j.created_at desc limit 1 for update;
    if found then return next v_existing; return; end if;
  end if;

  select e.plan,e.status,e.monthly_job_limit,e.current_period_start
    into v_plan,v_role,v_monthly_limit,v_period_start
    from public.entitlements e where e.workspace_id=target_workspace_id for update;
  if not found then
    v_plan := 'pilot'; v_role := 'active'; v_monthly_limit := 30; v_period_start := date_trunc('month',now());
  end if;
  if v_role not in ('active','trialing') then raise exception 'workspace plan is not active'; end if;
  select count(*) into v_job_count from public.jobs j
    where j.workspace_id=target_workspace_id
      and j.created_at >= coalesce(v_period_start,date_trunc('month',now()));
  if v_job_count >= v_monthly_limit then raise exception 'monthly workspace job limit reached'; end if;

  v_max_concurrent := coalesce(nullif(target_input->>'max_concurrent_jobs','')::integer,1);
  if v_max_concurrent not between 1 and 32 then raise exception 'invalid project concurrency limit'; end if;
  if target_input ? 'max_project_estimate_usd' and target_input->>'max_project_estimate_usd' is not null then
    if target_input->>'max_project_estimate_usd' !~ '^[0-9]+(\.[0-9]+)?$' then raise exception 'invalid project budget limit'; end if;
    v_limit := (target_input->>'max_project_estimate_usd')::numeric;
    select coalesce(sum(case e.event_type
      when 'reservation' then e.amount
      when 'actual' then e.amount
      when 'release' then -e.amount
      when 'refund' then -e.amount
      else e.amount end),0)
      into v_committed from public.usage_events e
      where e.workspace_id=target_workspace_id and e.project_id=target_project_id;
    if v_committed + target_estimated_cost > v_limit then raise exception 'project production budget exhausted'; end if;
  end if;

  insert into public.jobs(workspace_id,project_id,operation,status,idempotency_key,input,created_by)
    values(target_workspace_id,target_project_id,target_operation,'queued',target_idempotency_key,target_input,target_created_by)
    returning * into v_job;
  insert into public.usage_events(workspace_id,project_id,job_id,event_type,provider,operation,quantity,amount,idempotency_key,metadata)
    values(target_workspace_id,target_project_id,v_job.id,'reservation',target_provider,target_operation,1,target_estimated_cost,
      'job:'||v_job.id::text||':reservation',jsonb_build_object('source','hosted_mcp','estimate_only',true));
  return next v_job;
end; $$;

create or replace function public.claim_studio_job(worker_name text,lease_seconds integer default 300)
returns setof public.jobs language plpgsql security definer set search_path=''
as $$
declare
  candidate public.jobs%rowtype;
  active_count integer;
  max_concurrent integer;
begin
  if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
  if worker_name is null or length(trim(worker_name)) not between 1 and 120 then raise exception 'invalid worker name'; end if;
  if lease_seconds not between 30 and 1800 then raise exception 'lease must be between 30 and 1800 seconds'; end if;
  for candidate in
    select j.* from public.jobs j where j.status='queued'
    order by j.created_at for update skip locked limit 100
  loop
    perform pg_advisory_xact_lock(hashtextextended(candidate.workspace_id::text||':'||candidate.project_id::text,0));
    max_concurrent := coalesce(nullif(candidate.input->>'max_concurrent_jobs','')::integer,1);
    select count(*) into active_count from public.jobs j
      where j.workspace_id=candidate.workspace_id and j.project_id=candidate.project_id
        and j.status in ('running','cancelling');
    if active_count >= max_concurrent then continue; end if;
    if exists (
      select 1 from jsonb_array_elements_text(coalesce(candidate.input->'depends_on','[]'::jsonb)) dep(step_id)
      where not exists (
        select 1 from public.jobs prior where prior.workspace_id=candidate.workspace_id
          and prior.project_id=candidate.project_id and prior.status='succeeded'
          and prior.input->>'plan_id'=candidate.input->>'plan_id'
          and prior.input->>'step_id'=dep.step_id
      )
    ) then continue; end if;
    update public.jobs j set status='running',lease_owner=worker_name,
      lease_expires_at=now()+make_interval(secs=>lease_seconds),
      started_at=coalesce(j.started_at,now()),attempt=j.attempt+1,updated_at=now()
      where j.id=candidate.id returning j.* into candidate;
    return next candidate;
    return;
  end loop;
end; $$;

create or replace function public.heartbeat_studio_job(target_job_id uuid,worker_name text,lease_seconds integer default 300)
returns boolean language plpgsql security definer set search_path=''
as $$
declare changed integer;
begin
  if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
  if lease_seconds not between 30 and 1800 then raise exception 'lease must be between 30 and 1800 seconds'; end if;
  update public.jobs set lease_expires_at=now()+make_interval(secs=>lease_seconds),updated_at=now()
    where id=target_job_id and status in ('running','cancelling') and lease_owner=worker_name and lease_expires_at>now();
  get diagnostics changed=row_count;
  return changed=1;
end; $$;

create function public.reconcile_studio_job(target_job_id uuid,worker_name text,reason text)
returns boolean language plpgsql security definer set search_path=''
as $$
declare changed integer;
begin
  if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
  update public.jobs set status='reconciling',lease_owner=null,lease_expires_at=null,updated_at=now(),
    error=jsonb_build_object('reason',left(coalesce(reason,'uncertain_provider_outcome'),160),'automatic_retry',false)
    where id=target_job_id and status in ('running','cancelling') and lease_owner=worker_name and lease_expires_at>now();
  get diagnostics changed=row_count;
  return changed=1;
end; $$;

create or replace function public.report_studio_job_progress(target_job_id uuid,worker_name text,progress_value smallint,stage_label text default '')
returns boolean language plpgsql security definer set search_path=''
as $$
declare changed integer;
begin
  if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
  if progress_value not between 0 and 99 then raise exception 'progress must be between 0 and 99'; end if;
  if length(coalesce(stage_label,''))>160 then raise exception 'progress label is too long'; end if;
  update public.jobs set progress=greatest(progress,progress_value),progress_label=coalesce(stage_label,''),updated_at=now()
    where id=target_job_id and status='running' and lease_owner=worker_name and lease_expires_at>now();
  get diagnostics changed=row_count;
  return changed=1;
end; $$;

create or replace function public.finish_studio_job(target_job_id uuid,worker_name text,succeeded boolean,job_result jsonb default null,job_error jsonb default null)
returns boolean language plpgsql security definer set search_path=''
as $$
declare
  changed integer;
  current_job public.jobs%rowtype;
  actual_amount numeric;
  reserved_amount numeric;
begin
  if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
  if succeeded and job_error is not null then raise exception 'successful job cannot include an error'; end if;
  if not succeeded and job_error is null then raise exception 'failed job requires an error detail'; end if;
  if pg_column_size(coalesce(job_result,'null'::jsonb))>2097152 or pg_column_size(coalesce(job_error,'null'::jsonb))>65536 then
    raise exception 'job result or error exceeds the storage limit';
  end if;
  select * into current_job from public.jobs where id=target_job_id for update;
  if not found or current_job.status not in ('running','cancelling') or current_job.lease_owner<>worker_name
    or current_job.lease_expires_at<=now() then return false; end if;
  if succeeded and current_job.status='cancelling' then succeeded := false; end if;
  if succeeded and job_result ? 'cost_usd' and jsonb_typeof(job_result->'cost_usd')='number' then
    actual_amount := (job_result->>'cost_usd')::numeric;
    if actual_amount<0 or actual_amount::text in ('NaN','Infinity','-Infinity') then raise exception 'invalid actual cost'; end if;
  end if;
  update public.jobs set status=case when current_job.status='cancelling' then 'cancelled' when succeeded then 'succeeded' else 'failed' end,
    progress=case when succeeded then 100 else progress end,
    result=case when succeeded then job_result else null end,
    error=case when succeeded then null else coalesce(job_error,'{"reason":"cancelled"}'::jsonb) end,
    finished_at=now(),lease_owner=null,lease_expires_at=null,updated_at=now()
    where id=target_job_id and status in ('running','cancelling') and lease_owner=worker_name;
  get diagnostics changed=row_count;
  if changed=1 and succeeded and actual_amount is not null then
    reserved_amount := coalesce(nullif(current_job.input->>'estimated_cost_usd','')::numeric,0);
    insert into public.usage_events(workspace_id,project_id,job_id,event_type,provider,operation,quantity,amount,idempotency_key,metadata)
      values(current_job.workspace_id,current_job.project_id,current_job.id,'actual',nullif(current_job.input->>'provider',''),current_job.operation,1,actual_amount,
        'job:'||current_job.id::text||':actual',jsonb_build_object('source','hosted_mcp')) on conflict(workspace_id,idempotency_key) do nothing;
    insert into public.usage_events(workspace_id,project_id,job_id,event_type,provider,operation,quantity,amount,idempotency_key,metadata)
      values(current_job.workspace_id,current_job.project_id,current_job.id,'release',nullif(current_job.input->>'provider',''),current_job.operation,1,reserved_amount,
        'job:'||current_job.id::text||':release',jsonb_build_object('source','hosted_mcp','reservation_settled',true)) on conflict(workspace_id,idempotency_key) do nothing;
  end if;
  return changed=1;
end; $$;

create or replace function public.cancel_studio_job(target_workspace_id uuid,target_project_id uuid,target_job_id uuid)
returns public.jobs language plpgsql security definer set search_path=''
as $$
declare current_job public.jobs%rowtype;
begin
  if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
  select * into current_job from public.jobs where id=target_job_id and workspace_id=target_workspace_id and project_id=target_project_id for update;
  if not found then raise exception 'job is not available in this workspace' using errcode='42501'; end if;
  if current_job.status='queued' then
    update public.jobs set status='cancelled',finished_at=now(),updated_at=now(),error='{"reason":"cancelled_before_execution"}'::jsonb
      where id=target_job_id returning * into current_job;
    insert into public.usage_events(workspace_id,project_id,job_id,event_type,provider,operation,quantity,amount,idempotency_key,metadata)
      values(current_job.workspace_id,current_job.project_id,current_job.id,'release',nullif(current_job.input->>'provider',''),current_job.operation,1,
        coalesce(nullif(current_job.input->>'estimated_cost_usd','')::numeric,0),'job:'||current_job.id::text||':release',
        jsonb_build_object('source','hosted_mcp','cancelled_before_execution',true)) on conflict(workspace_id,idempotency_key) do nothing;
  elsif current_job.status='running' then
    update public.jobs set status='cancelling',updated_at=now() where id=target_job_id returning * into current_job;
  end if;
  return current_job;
end; $$;

create or replace function public.reconcile_expired_studio_jobs()
returns integer language plpgsql security definer set search_path=''
as $$
declare changed integer;
begin
  if auth.role() <> 'service_role' then raise exception 'service role required' using errcode='42501'; end if;
  update public.jobs set status='reconciling',lease_owner=null,lease_expires_at=null,updated_at=now(),
    error=coalesce(error,'{}'::jsonb)||jsonb_build_object('reason','worker_lease_expired','automatic_retry',false)
    where status in ('running','cancelling') and lease_expires_at<=now();
  get diagnostics changed=row_count;
  return changed;
end; $$;

revoke all on function public.enqueue_studio_job(uuid,uuid,text,text,uuid,jsonb,numeric,text),
  public.claim_studio_job(text,integer),public.heartbeat_studio_job(uuid,text,integer),
  public.report_studio_job_progress(uuid,text,smallint,text),public.finish_studio_job(uuid,text,boolean,jsonb,jsonb),
  public.reconcile_studio_job(uuid,text,text),public.cancel_studio_job(uuid,uuid,uuid),
  public.reconcile_expired_studio_jobs() from public,authenticated,anon;
grant execute on function public.enqueue_studio_job(uuid,uuid,text,text,uuid,jsonb,numeric,text),
  public.claim_studio_job(text,integer),public.heartbeat_studio_job(uuid,text,integer),
  public.report_studio_job_progress(uuid,text,smallint,text),public.finish_studio_job(uuid,text,boolean,jsonb,jsonb),
  public.reconcile_studio_job(uuid,text,text),public.cancel_studio_job(uuid,uuid,uuid),
  public.reconcile_expired_studio_jobs() to service_role;
