'use client';

import { useActionState } from 'react';
import { ArrowUpRight, Check, PlugZap } from 'lucide-react';
import { connectStudioEngine, revokeStudioEngineConnection, type EngineConnectionActionState } from '../actions';

type Connection = { id: string; label: string; status: string; last_seen_at: string | null };
const initialState: EngineConnectionActionState = {};

export default function ConnectEngine({ workspaceId, role, endpoint, connections, storageReady }: {
  workspaceId: string;
  role: string;
  endpoint: string;
  connections: Connection[];
  storageReady: boolean;
}) {
  const [state, action, pending] = useActionState(connectStudioEngine, initialState);
  const canManage = ['owner', 'admin'].includes(role);
  const connected = connections.some(item => item.status === 'connected');
  const canConnect = Boolean(endpoint && storageReady);
  return <section id="engine" className="engine-panel" aria-labelledby="engine-title">
    <div className="recent-head"><div><h2 id="engine-title">Connect the video engine</h2></div><span className={`engine-indicator ${connected ? 'is-connected' : ''}`}><i />{connected ? 'CONNECTED' : endpoint && storageReady ? 'NOT CONNECTED' : 'SETUP NEEDED'}</span></div>
    {!endpoint ? <p className="engine-setup-note"><strong>Studio needs an engine URL.</strong> Add <code>NEXT_PUBLIC_MCP_ENDPOINT</code> to the Studio server environment. It must be a reachable HTTPS MCP endpoint.</p> : null}
    {!storageReady ? <p className="engine-setup-note"><strong>Studio secure storage is not ready.</strong> Confirm <code>SUPABASE_SERVICE_ROLE_KEY</code> and <code>STUDIO_CREDENTIAL_ENCRYPTION_KEY</code> are configured as server-only environment variables, then restart Studio.</p> : null}
    {endpoint && storageReady ? <p className="engine-intro">Studio checks the MCP handshake and encrypts its workspace token on the server. The token is never shown in your browser.</p> : null}
    {connections.length ? <ul className="engine-list">{connections.map(connection => <li key={connection.id}><PlugZap aria-hidden="true" /><span><strong>{connection.label}</strong><small>{connection.last_seen_at ? `Last checked ${connection.last_seen_at.slice(0, 16).replace('T', ' ')} UTC` : 'No successful handshake yet'}</small></span><b className={`engine-status engine-status-${connection.status}`}>{connection.status.replaceAll('_', ' ').toUpperCase()}</b>{canManage && connection.status !== 'revoked' ? <form action={revokeStudioEngineConnection} onSubmit={event => {
      if (!window.confirm(`Disconnect “${connection.label}”? Studio will revoke its workspace token.`)) event.preventDefault();
    }}><input type="hidden" name="workspace_id" value={workspaceId} /><input type="hidden" name="connection_id" value={connection.id} /><button className="engine-revoke" type="submit">Disconnect</button></form> : null}</li>)}</ul> : <p className="engine-empty">No engine connection has been checked yet.</p>}
    {canManage ? <form action={action} className="engine-form"><input type="hidden" name="workspace_id" value={workspaceId} /><div className="field"><label htmlFor="engine-label">Connection name</label><input id="engine-label" name="label" autoComplete="off" maxLength={120} required placeholder="Primary OpenMontage server" /></div><button type="submit" disabled={pending || !canConnect}>{pending ? 'Checking engine…' : 'Connect and check tools'} <ArrowUpRight aria-hidden="true" /></button>
      {state.error ? <p className="engine-error" role="alert">{state.error}</p> : null}
      {state.connected ? <p className="engine-success" role="status" aria-live="polite"><Check aria-hidden="true" />{state.connected}</p> : null}
    </form> : <p className="engine-empty">Only workspace owners and admins can connect an engine.</p>}
  </section>;
}
