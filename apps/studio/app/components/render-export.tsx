'use client';

import { useActionState } from 'react';
import { Download, LoaderCircle, Play } from 'lucide-react';
import { loadStudioRender, type StudioRenderState } from '../actions';

const initialState: StudioRenderState = {};

function fileSize(bytes: number) {
  if (bytes < 1_000_000) return `${Math.max(1, Math.round(bytes / 1_000))} KB`;
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

export default function RenderExport({ workspaceId, projectId }: {
  workspaceId: string;
  projectId: string;
}) {
  const [state, action, pending] = useActionState(loadStudioRender, initialState);

  return <section className="render-export" aria-label="Video render and export">
    <form action={action}>
      <input type="hidden" name="workspace_id" value={workspaceId} />
      <input type="hidden" name="project_id" value={projectId} />
      <button type="submit" disabled={pending}>
        {pending ? <LoaderCircle className="research-spinner" aria-hidden="true" /> : <Play aria-hidden="true" />}
        {pending ? 'Finding your render…' : state.render ? 'Refresh preview link' : 'Preview or export video'}
      </button>
    </form>
    {state.error ? <p className="research-message research-error" role="alert">{state.error}</p> : null}
    {state.message ? <p className="research-message" role="status">{state.message}</p> : null}
    {state.render ? <div className="render-card">
      <video controls playsInline preload="metadata" src={state.render.url} aria-label={`Preview of ${state.render.filename}`} />
      <div className="render-meta"><span><strong>{state.render.filename}</strong><small>{fileSize(state.render.bytes)} · link expires in {Math.max(1, Math.ceil(state.render.expiresInSeconds / 60))} min</small></span>
        <a href={state.render.url} download={state.render.filename}><Download aria-hidden="true" /> Download</a></div>
    </div> : null}
  </section>;
}
