'use client';

import { useActionState } from 'react';
import { ArrowDownToLine, LoaderCircle, RefreshCw } from 'lucide-react';
import { refreshStudioClips, type ClipRefreshState } from '../actions';

const initialState: ClipRefreshState = {};

export default function ClipResults({ workspaceId, projectId, initialStatus, initialClips }: {
  workspaceId: string;
  projectId: string;
  initialStatus: string;
  initialClips: Array<{ title: string; url: string }>;
}) {
  const [state, action, pending] = useActionState(refreshStudioClips, initialState);
  const clips = state.clips || initialClips;
  return <div className="clip-job-results">
    <form action={action}>
      <input type="hidden" name="workspace_id" value={workspaceId} />
      <input type="hidden" name="project_id" value={projectId} />
      <button type="submit" disabled={pending}>
        {pending ? <LoaderCircle className="research-spinner" aria-hidden="true" /> : <RefreshCw aria-hidden="true" />}
        {pending ? 'Checking OpenShorts…' : clips.length ? 'Refresh clip status' : 'Check clip progress'}
      </button>
      <span>{initialStatus ? `Latest saved status: ${initialStatus.replaceAll('_', ' ')}` : 'OpenShorts processing may take several minutes.'}</span>
    </form>
    {state.error ? <p className="clip-refresh-error" role="alert">{state.error}</p> : null}
    {state.message ? <p className="clip-refresh-message" role="status">{state.message}</p> : null}
    {clips.length ? <ul className="clip-download-list">{clips.map(clip => <li key={clip.url}><strong>{clip.title}</strong><a href={clip.url} target="_blank" rel="noreferrer"><ArrowDownToLine aria-hidden="true" /> Download clip</a></li>)}</ul> : null}
  </div>;
}
