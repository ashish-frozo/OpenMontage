'use client';

import { useActionState, useState } from 'react';
import { createWorkspaceMcpToken, revokeWorkspaceMcpToken, type McpTokenActionState } from '../actions';

type Token = { id: string; label: string; scopes: string[]; created_at: string; expires_at: string; revoked_at: string | null; last_used_at: string | null };
const initialState: McpTokenActionState = {};

export default function McpAccess({ workspaceId, role, endpoint, tokens }: {
  workspaceId: string;
  role: string;
  endpoint: string;
  tokens: Token[];
}) {
  const [state, action, pending] = useActionState(createWorkspaceMcpToken, initialState);
  const [copied, setCopied] = useState(false);
  const canManage = ['owner', 'admin'].includes(role);
  return <section id="mcp-access" className="mcp-access" aria-labelledby="mcp-access-title">
    <div className="recent-head"><div><span className="eyebrow">CONNECT AN AI TOOL</span><h2 id="mcp-access-title">OpenMontage MCP</h2></div><span className="project-total">WORKSPACE SCOPED</span></div>
    {endpoint ? <p className="mcp-endpoint"><span>Server endpoint</span><code>{endpoint}</code></p> : <p className="mcp-endpoint mcp-unconfigured">The hosted MCP endpoint is not configured for this Studio deployment yet.</p>}
    <p className="mcp-explainer">Create a bearer token for an MCP client. It grants access to this workspace’s projects and keeps the existing pipeline approvals and cost checks in effect. Tokens expire after 90 days.</p>
    {tokens.length ? <ul className="mcp-token-list">{tokens.map(token => <li key={token.id}>
      <span className="token-glyph" aria-hidden="true">⌘</span>
      <span className="token-copy"><strong>{token.label}</strong><small>{token.scopes.join(', ')} · expires {token.expires_at.slice(0, 10)}</small>{token.last_used_at ? <small>Last used {token.last_used_at.slice(0, 16).replace('T', ' ')} UTC</small> : null}</span>
      <span className={`token-state ${token.revoked_at ? 'is-revoked' : Date.parse(token.expires_at) <= Date.now() ? 'is-expired' : ''}`}>{token.revoked_at ? 'REVOKED' : Date.parse(token.expires_at) <= Date.now() ? 'EXPIRED' : 'ACTIVE'}</span>
      {canManage && !token.revoked_at ? <form action={revokeWorkspaceMcpToken} onSubmit={event => {
        if (!window.confirm(`Revoke the MCP token “${token.label}”? Connected tools will lose access to this workspace.`)) event.preventDefault();
      }}><input type="hidden" name="workspace_id" value={workspaceId} /><input type="hidden" name="token_id" value={token.id} /><button className="token-revoke" type="submit">Revoke</button></form> : null}
    </li>)}</ul> : <p className="mcp-empty">No MCP access tokens yet. Create one to connect an AI client to this workspace.</p>}
    {canManage ? <form action={action} className="mcp-token-form">
      <input type="hidden" name="workspace_id" value={workspaceId} />
      <div className="field"><label htmlFor="mcp-token-label">Token label</label><input id="mcp-token-label" name="label" required maxLength={120} placeholder="My writing assistant" autoComplete="off" /></div>
      <div className="field"><label htmlFor="mcp-token-access">Access level</label><select id="mcp-token-access" name="access_level" defaultValue="read-write"><option value="read-only">Read only · browse projects and plans</option><option value="read-write">Production · create projects and run approved work</option></select><small>Every token can read. Production access is required to change project data or submit work.</small></div>
      <button type="submit" disabled={pending}>{pending ? 'Creating…' : 'Create MCP token'}</button>
      {state.error ? <p className="mcp-form-message" role="alert">{state.error}</p> : null}
      {state.token ? <div className="token-once" role="status"><b>Copy this token now</b><p>It is shown once. OpenMontage stores only its hash.</p><code>{state.token}</code><button type="button" onClick={async () => {
        await navigator.clipboard.writeText(state.token!);
        setCopied(true);
      }}>{copied ? 'Copied' : 'Copy token'}</button></div> : null}
    </form> : <p className="mcp-empty">Only workspace owners and admins can create or revoke MCP tokens.</p>}
  </section>;
}
