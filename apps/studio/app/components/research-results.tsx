'use client';

import { useActionState } from 'react';
import { ExternalLink, LoaderCircle, SearchCheck } from 'lucide-react';
import { loadStudioResearchResult, type ResearchResultState } from '../actions';

const initialState: ResearchResultState = {};

export default function ResearchResults({ workspaceId, projectId, status, currentStage }: {
  workspaceId: string;
  projectId: string;
  status: string;
  currentStage: string | null;
}) {
  const [state, action, pending] = useActionState(loadStudioResearchResult, initialState);
  if (status !== 'research' && currentStage !== 'research') return null;

  return <section className="research-review" aria-label="Research source leads">
    <form action={action}>
      <input type="hidden" name="workspace_id" value={workspaceId} />
      <input type="hidden" name="project_id" value={projectId} />
      <button type="submit" disabled={pending}>
        {pending ? <LoaderCircle className="research-spinner" aria-hidden="true" /> : <SearchCheck aria-hidden="true" />}
        {pending ? 'Checking research…' : state.leads ? 'Refresh source leads' : 'Review source leads'}
      </button>
    </form>
    {state.error ? <p className="research-message research-error" role="alert">{state.error}</p> : null}
    {state.message ? <p className="research-message" role="status">{state.message}</p> : null}
    {state.leads?.length ? <div className="research-leads" aria-live="polite">
      <p className="research-query">Search: <strong>{state.query || 'Saved brief topic'}</strong></p>
      <p className="research-caveat">Discovery leads only. Check the original sources before treating a claim as fact.</p>
      <ol>{state.leads.map((lead, index) => <li key={`${lead.url}-${index}`}>
        <a href={lead.url} target="_blank" rel="noreferrer">{lead.title}<ExternalLink aria-hidden="true" /></a>
        {lead.snippet ? <p>{lead.snippet}</p> : null}
      </li>)}</ol>
    </div> : null}
  </section>;
}
