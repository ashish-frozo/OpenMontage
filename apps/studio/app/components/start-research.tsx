'use client';

import { useActionState } from 'react';
import { ArrowUpRight, LoaderCircle, Search } from 'lucide-react';
import { startStudioResearch, type StartResearchState } from '../actions';

const initialState: StartResearchState = {};

export default function StartResearch({ workspaceId, projectId, status }: {
  workspaceId: string;
  projectId: string;
  status: string;
}) {
  const [state, action, pending] = useActionState(startStudioResearch, initialState);

  if (status !== 'brief') {
    return status === 'research'
      ? <a className="research-running" href="#activity"><LoaderCircle aria-hidden="true" /> Check activity</a>
      : null;
  }

  return <div className="research-action">
    <form action={action}>
      <input type="hidden" name="workspace_id" value={workspaceId} />
      <input type="hidden" name="project_id" value={projectId} />
      <button type="submit" disabled={pending} aria-label="Start free Wikipedia research, estimated cost zero dollars">
        {pending ? <LoaderCircle className="research-spinner" aria-hidden="true" /> : <Search aria-hidden="true" />}
        {pending ? 'Starting research…' : 'Start free research'}
        {!pending ? <ArrowUpRight aria-hidden="true" /> : null}
      </button>
    </form>
    <small>Wikipedia · 5 results · $0.00</small>
    {state.error ? <p className="research-message research-error" role="alert">{state.error}</p> : null}
    {state.submitted ? <p className="research-message" role="status">{state.submitted}</p> : null}
  </div>;
}
