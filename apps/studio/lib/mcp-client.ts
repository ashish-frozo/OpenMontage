type RpcEnvelope = { result?: unknown; error?: { message?: string } };
type McpTool = { name: string; description?: string; inputSchema?: Record<string, unknown> };
export type McpClient = {
  listTools(): Promise<McpTool[]>;
  callTool(name: string, arguments_: Record<string, unknown>): Promise<unknown>;
};

async function readRpcResponse(response: Response): Promise<RpcEnvelope> {
  if (!response.ok) throw new Error(`MCP returned HTTP ${response.status}`);
  const contentType = response.headers.get('content-type') || '';
  const text = await response.text();
  if (text.length > 1_000_000) throw new Error('MCP response exceeded 1 MB');
  let payload: RpcEnvelope;
  if (contentType.includes('application/json')) {
    payload = JSON.parse(text) as RpcEnvelope;
  } else if (contentType.includes('text/event-stream')) {
    const data = text.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
    if (!data) throw new Error('MCP returned an empty event stream');
    payload = JSON.parse(data) as RpcEnvelope;
  } else {
    throw new Error('MCP returned an unsupported response type');
  }
  if (payload.error) throw new Error(payload.error.message || 'MCP request failed');
  return payload;
}

export async function connectMcpClient(endpoint: string, token: string): Promise<McpClient> {
  const url = new URL(endpoint);
  if (!['https:', 'http:'].includes(url.protocol) || (url.protocol === 'http:' && !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) {
    throw new Error('The configured MCP endpoint must use HTTPS. HTTP is allowed only for localhost development.');
  }
  if (url.username || url.password || url.search || url.hash) throw new Error('The configured MCP endpoint contains unsupported URL parts.');

  let nextId = 1;
  let sessionId: string | null = null;
  let protocolVersion = '2025-03-26';
  let handshakeComplete = false;
  const request = async (method: string, params: Record<string, unknown>, id?: number): Promise<RpcEnvelope> => {
    const headers: Record<string, string> = {
      authorization: `Bearer ${token}`,
      accept: 'application/json, text/event-stream',
      'content-type': 'application/json',
    };
    if (handshakeComplete) headers['mcp-protocol-version'] = protocolVersion;
    if (sessionId) {
      headers['mcp-session-id'] = sessionId;
    }
    const body = id === undefined
      ? { jsonrpc: '2.0', method, params }
      : { jsonrpc: '2.0', id, method, params };
    const response = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body), signal: AbortSignal.timeout(15_000), cache: 'no-store', redirect: 'error' });
    const returnedSession = response.headers.get('mcp-session-id');
    if (returnedSession) sessionId = returnedSession;
    if (id === undefined) {
      if (response.status !== 202 && !response.ok) throw new Error(`MCP returned HTTP ${response.status}`);
      return {};
    }
    return readRpcResponse(response);
  };

  const initializeResponse = await request('initialize', {
    protocolVersion,
    capabilities: {},
    clientInfo: { name: 'OpenMontage Studio', version: '0.1.0' },
  }, nextId++);
  const initResult = initializeResponse.result as { protocolVersion?: string } | undefined;
  if (!initResult || typeof initResult !== 'object') throw new Error('MCP did not complete initialization');
  if (typeof initResult.protocolVersion === 'string') protocolVersion = initResult.protocolVersion;
  handshakeComplete = true;
  await request('notifications/initialized', {});

  const listTools = async (): Promise<McpTool[]> => {
    const tools: McpTool[] = [];
    let cursor: string | undefined;
    const cursors = new Set<string>();
    do {
      const response = await request('tools/list', cursor ? { cursor } : {}, nextId++);
      const result = response.result as { tools?: McpTool[]; nextCursor?: string } | undefined;
      if (!result || !Array.isArray(result.tools)) throw new Error('MCP did not return a tool list');
      tools.push(...result.tools.filter((tool): tool is McpTool => Boolean(tool && typeof tool.name === 'string' && tool.name.length <= 120)));
      const next = typeof result.nextCursor === 'string' ? result.nextCursor : undefined;
      if (!next || tools.length >= 200) break;
      if (cursors.has(next)) throw new Error('MCP repeated a tool-list cursor');
      cursors.add(next);
      cursor = next;
    } while (true);
    return tools.slice(0, 200);
  };
  const callTool = async (name: string, arguments_: Record<string, unknown>): Promise<unknown> => {
    if (!/^[a-zA-Z0-9_.-]{1,120}$/.test(name)) throw new Error('Invalid MCP tool name');
    const response = await request('tools/call', { name, arguments: arguments_ }, nextId++);
    const result = response.result as { content?: Array<{ type?: string; text?: string }>; structuredContent?: unknown; isError?: boolean } | undefined;
    if (!result || typeof result !== 'object') throw new Error('MCP returned an invalid tool result');
    if (result.isError) {
      const detail = (result.content || []).filter(item => item.type === 'text' && item.text).map(item => item.text).join('\n').slice(0, 1200);
      throw new Error(detail || 'MCP tool call failed');
    }
    if (result.structuredContent !== undefined) return result.structuredContent;
    const text = (result.content || []).filter(item => item.type === 'text' && item.text).map(item => item.text).join('\n');
    if (!text) return result.content || [];
    try { return JSON.parse(text) as unknown; } catch { return text; }
  };
  return { listTools, callTool };
}

export async function listMcpTools(endpoint: string, token: string): Promise<McpTool[]> {
  return (await connectMcpClient(endpoint, token)).listTools();
}

export function capabilityStage(toolName: string): string {
  const name = toolName.toLowerCase();
  if (/research|search|fetch|trend|source/.test(name)) return 'research';
  if (/script|story|narrat/.test(name)) return 'script';
  if (/scene|storyboard|shot|image|voice|audio|music|asset|stock|motion/.test(name)) return 'assets';
  if (/edit|timeline|subtitle|caption/.test(name)) return 'edit';
  if (/compose|render|video|export/.test(name)) return 'compose';
  if (/publish|delivery|analytics|performance/.test(name)) return 'publish';
  return 'workspace';
}
