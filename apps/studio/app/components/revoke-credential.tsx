'use client';

import { revokeProviderCredential } from '../actions';

export default function RevokeCredential({ workspaceId, connectionId }: { workspaceId: string; connectionId: string }) {
  return <form action={revokeProviderCredential} onSubmit={(event) => {
    if (!window.confirm('Permanently remove this encrypted provider key from the workspace? You can add it again later.')) {
      event.preventDefault();
    }
  }}>
    <input type="hidden" name="workspace_id" value={workspaceId} />
    <input type="hidden" name="connection_id" value={connectionId} />
    <button className="provider-revoke" type="submit">Revoke key</button>
  </form>;
}
