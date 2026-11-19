'use client';

import { useCallback, useEffect, useState } from 'react';
import { createClient } from '@/lib/supabase/client';

type Job = {
  id: string;
  project_id: string;
  operation: string;
  status: string;
  progress: number;
  progress_label: string;
  created_at: string;
  updated_at: string;
};
type Project = { id: string; title: string };

function statusLabel(status: string) {
  return status.replaceAll('_', ' ').toUpperCase();
}

export default function JobActivity({ workspaceId, projects, initialJobs, initialUnavailable = false }: {
  workspaceId: string;
  projects: Project[];
  initialJobs: Job[];
  initialUnavailable?: boolean;
}) {
  const [jobs, setJobs] = useState(initialJobs);
  const [unavailable, setUnavailable] = useState(initialUnavailable);

  const refresh = useCallback(async () => {
    const supabase = createClient();
    const { data, error } = await supabase.from('jobs')
      .select('id,project_id,operation,status,progress,progress_label,created_at,updated_at')
      .eq('workspace_id', workspaceId)
      .order('updated_at', { ascending: false })
      .limit(10);
    if (error) {
      setUnavailable(true);
      return;
    }
    setJobs((data || []) as Job[]);
    setUnavailable(false);
  }, [workspaceId]);

  useEffect(() => {
    let inFlight = false;
    const poll = () => {
      if (document.visibilityState !== 'visible' || inFlight) return;
      inFlight = true;
      void refresh().finally(() => { inFlight = false; });
    };
    const interval = window.setInterval(poll, 8000);
    document.addEventListener('visibilitychange', poll);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', poll);
    };
  }, [refresh]);

  const titleById = new Map(projects.map(project => [project.id, project.title]));
  return <section id="activity" className="recent job-activity" aria-labelledby="activity-title">
    <div className="recent-head"><div><span className="eyebrow">LIVE WORK QUEUE</span><h2 id="activity-title">Production activity</h2></div><span className="project-total">{jobs.length} recent</span></div>
    {unavailable ? <p className="activity-empty" role="status">Job activity could not refresh. Your workspace access may have expired; reload Studio to reconnect.</p> : null}
    {!jobs.length && !unavailable ? <p className="activity-empty">Jobs will appear here when a connected engine submits a validated pipeline step.</p> : null}
    {jobs.length ? <ul className="job-list">{jobs.map(job => {
      return <li key={job.id}>
        <div className="job-line"><span className={`job-state job-${job.status}`}><i aria-hidden="true" />{statusLabel(job.status)}</span><time dateTime={job.updated_at}>{job.updated_at.slice(0, 16).replace('T', ' ')} UTC</time></div>
        <strong className="job-name">{job.progress_label || job.operation.replaceAll('_', ' ')}</strong>
        <span className="job-project">{titleById.get(job.project_id) || 'Video project'}</span>
        {job.status === 'queued' ? <small className="job-guidance">Waiting for an available worker to start.</small> : null}
        {job.status === 'waiting_approval' ? <small className="job-guidance">Waiting for your approval. No work has started.</small> : null}
        {job.status === 'reconciling' ? <small className="job-guidance">The previous run needs a status check before anyone retries it.</small> : null}
        {job.status === 'running' ? job.progress > 0
          ? <progress max={100} value={Math.min(99, Math.max(1, job.progress))} aria-label={`${job.operation} progress`} />
          : <progress max={100} aria-label={`${job.operation} is running`} /> : null}
      </li>;
    })}</ul> : null}
  </section>;
}
