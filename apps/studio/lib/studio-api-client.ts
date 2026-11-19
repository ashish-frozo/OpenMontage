export type StudioApiClient = {
  callOperation(name: string, arguments_: Record<string, unknown>): Promise<unknown>;
};

export function connectStudioApi(baseUrl: string, accessToken: string, workspaceId: string): StudioApiClient {
  let origin: URL;
  try {
    origin = new URL(baseUrl);
  } catch {
    throw new Error('Studio worker API URL is not configured.');
  }
  if (!['https:', 'http:'].includes(origin.protocol)
    || (origin.protocol === 'http:' && !['localhost', '127.0.0.1', '[::1]'].includes(origin.hostname))
    || origin.username || origin.password || origin.search || origin.hash) {
    throw new Error('Studio worker API must use HTTPS and cannot contain credentials or query parameters.');
  }

  const base = origin.toString().replace(/\/$/, '');
  return {
    async callOperation(name, arguments_) {
      if (!/^[a-zA-Z0-9_.-]{1,120}$/.test(name)) throw new Error('Invalid Studio operation.');
      const response = await fetch(`${base}/v1/operations/${encodeURIComponent(name)}`, {
        method: 'POST',
        headers: {
          authorization: `Bearer ${accessToken}`,
          'content-type': 'application/json',
          accept: 'application/json',
        },
        body: JSON.stringify({ workspace_id: workspaceId, arguments: arguments_ }),
        signal: AbortSignal.timeout(30_000),
        cache: 'no-store',
        redirect: 'error',
      });
      const text = await response.text();
      if (text.length > 1_000_000) throw new Error('Studio API response exceeded 1 MB.');
      let payload: { result?: unknown; error?: string };
      try {
        payload = JSON.parse(text) as { result?: unknown; error?: string };
      } catch {
        throw new Error(`Studio API returned an invalid response (${response.status}).`);
      }
      if (!response.ok) throw new Error(payload.error || `Studio API returned HTTP ${response.status}.`);
      if (!Object.hasOwn(payload, 'result')) throw new Error('Studio API response is missing its result.');
      return payload.result;
    },
  };
}
