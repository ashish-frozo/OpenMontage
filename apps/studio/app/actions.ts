'use server';

import { createHash, randomBytes, randomUUID } from 'node:crypto';
import { isIP } from 'node:net';
import { redirect } from 'next/navigation';
import { revalidatePath } from 'next/cache';
import { createClient as createServiceClient } from '@supabase/supabase-js';
import { createClient } from '@/lib/supabase/server';
import { decryptCredential, encryptCredential } from '@/lib/credentials';
import { capabilityStage, connectMcpClient, listMcpTools, type McpClient } from '@/lib/mcp-client';
import { getStylePreset } from './style-presets';

function configured() {
  return Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY);
}

function siteUrl() {
  return process.env.NEXT_PUBLIC_SITE_URL || (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : 'http://localhost:3000');
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

async function studioMcpClient(workspaceId: string): Promise<McpClient> {
  const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (!serviceRoleKey || !supabaseUrl) throw new Error('Secure Studio engine access is not configured on this server.');
  const admin = createServiceClient(supabaseUrl, serviceRoleKey, {
    auth: { autoRefreshToken: false, persistSession: false, detectSessionInUrl: false },
  });
  const { data: connection, error: connectionError } = await admin.from('engine_connections')
    .select('id,endpoint_url,mcp_token_id,last_seen_at')
    .eq('workspace_id', workspaceId).eq('status', 'connected')
    .order('last_seen_at', { ascending: false }).limit(1).maybeSingle();
  if (connectionError || !connection?.mcp_token_id) throw new Error('Connect an OpenMontage MCP engine in Studio first.');
  const { data: tokenRow, error: tokenError } = await admin.from('workspace_mcp_tokens')
    .select('expires_at,revoked_at').eq('id', connection.mcp_token_id).eq('workspace_id', workspaceId).maybeSingle();
  if (tokenError || !tokenRow || tokenRow.revoked_at || Date.parse(tokenRow.expires_at) <= Date.now()) {
    throw new Error('The Studio engine token has expired or been revoked. Reconnect the engine.');
  }
  const { data: secretRow, error: secretError } = await admin.from('engine_secrets')
    .select('ciphertext,key_version').eq('connection_id', connection.id).eq('workspace_id', workspaceId).maybeSingle();
  if (secretError || !secretRow || typeof secretRow.ciphertext !== 'string' || !secretRow.ciphertext.startsWith('\\x')) {
    throw new Error('The encrypted Studio engine token is unavailable. Disconnect and reconnect the engine.');
  }
  let ciphertext: Buffer;
  try {
    ciphertext = Buffer.from(secretRow.ciphertext.slice(2), 'hex');
    if (ciphertext.length < 29 || ciphertext.toString('hex') !== secretRow.ciphertext.slice(2).toLowerCase()) throw new Error();
  } catch {
    throw new Error('The encrypted Studio engine token has an invalid format.');
  }
  let token: string;
  try {
    token = decryptCredential(ciphertext, String(secretRow.key_version));
  } catch {
    throw new Error('Studio could not decrypt the engine token. Check its encryption key configuration.');
  }
  return connectMcpClient(connection.endpoint_url, token);
}

export async function sendSignInLink(formData: FormData) {
  const email = String(formData.get('email') || '').trim().toLowerCase();
  if (!configured()) redirect('/?notice=configure-supabase');
  if (!email || email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) redirect('/?notice=invalid-email');

  const supabase = await createClient();
  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: `${siteUrl()}/auth/callback?next=/` },
  });
  if (error) {
    if (error.status === 429 || error.code === 'over_email_send_rate_limit') {
      redirect('/?notice=sign-in-rate-limited');
    }
    redirect('/?notice=sign-in-failed');
  }
  redirect('/?notice=check-email');
}

export async function signOut() {
  if (configured()) {
    const supabase = await createClient();
    await supabase.auth.signOut();
  }
  redirect('/');
}

export async function createWorkspace(formData: FormData) {
  if (!configured()) redirect('/?notice=configure-supabase');
  const name = String(formData.get('name') || '').trim();
  if (!name || name.length > 120) redirect('/?notice=invalid-workspace');

  const supabase = await createClient();
  const { data: claimsData } = await supabase.auth.getClaims();
  if (!claimsData?.claims?.sub) redirect('/?notice=sign-in');

  const slug = name.toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 70);
  if (!slug) redirect('/?notice=invalid-workspace');
  const { error } = await supabase.rpc('create_workspace', { workspace_name: name, workspace_slug: slug });
  if (error) redirect(error.code === '23505' ? '/?notice=workspace-name-taken' : '/?notice=workspace-failed');
  redirect('/?notice=workspace-created');
}

export async function saveBrief(formData: FormData) {
  if (!configured()) redirect('/?notice=configure-supabase');
  const title = String(formData.get('title') || '').trim();
  const audience = String(formData.get('audience') || '').trim();
  const workspaceId = String(formData.get('workspace_id') || '');
  const platform = String(formData.get('platform') || '');
  const format = String(formData.get('format') || '');
  const goal = String(formData.get('goal') || '');
  const region = String(formData.get('region') || '').trim();
  const researchFreshness = String(formData.get('research_freshness') || '');
  const duration = String(formData.get('duration') || '');
  const pipeline = String(formData.get('pipeline') || '');
  const stylePreset = getStylePreset(String(formData.get('visual_style') || ''));
  if (!title || title.length > 240 || audience.length > 120) redirect('/?notice=invalid-brief');
  if (!/^[0-9a-f-]{36}$/i.test(workspaceId)) redirect('/?notice=invalid-workspace');
  if (!['youtube', 'instagram', 'multi'].includes(platform)) redirect('/?notice=invalid-platform');
  if (!['vertical', 'landscape', 'square'].includes(format)) redirect('/?notice=invalid-format');
  if (!['teach', 'entertain', 'inspire', 'persuade'].includes(goal) || region.length > 120) redirect('/?notice=invalid-brief');
  if (!['evergreen', 'current', 'last_30_days'].includes(researchFreshness)) redirect('/?notice=invalid-brief');
  if (!['30_60', '60_90', '180_300'].includes(duration)) redirect('/?notice=invalid-brief');
  if (!['animated-explainer', 'documentary-montage', 'talking-head', 'screen-demo', 'podcast-repurpose', 'cinematic', 'animation'].includes(pipeline) || !stylePreset) redirect('/?notice=invalid-brief');

  const supabase = await createClient();
  const { data: claimsData } = await supabase.auth.getClaims();
  const userId = claimsData?.claims?.sub;
  if (!userId) redirect('/?notice=sign-in');

  const { data: brandProfile } = await supabase.from('workspace_brand_profiles')
    .select('brand_name,audience,voice,visual_direction,avoid_terms,color_palette')
    .eq('workspace_id', workspaceId).maybeSingle();

  const { error } = await supabase.from('projects').insert({
    workspace_id: workspaceId,
    created_by: userId,
    title,
    platform,
    format,
    status: 'brief',
    brief: {
      version: 1,
      idea: title,
      audience,
      goal,
      region,
      research_freshness: researchFreshness,
      platform,
      format,
      pipeline,
      visual_style: { id: stylePreset.id, name: stylePreset.name, description: stylePreset.description, category: stylePreset.category, playbook: stylePreset.playbook },
      duration_seconds: duration === '30_60' ? [30, 60] : duration === '60_90' ? [60, 90] : [180, 300],
      research_requirements: { cite_sources: true, distinguish_fact_from_interpretation: true },
      brand_profile: brandProfile || null,
      status: 'ready_for_research',
    },
  });
  if (error) redirect(error.code === '42501' || error.code === '23503' ? '/?notice=workspace-access' : '/?notice=brief-failed');
  redirect('/?notice=brief-saved#projects');
}

export async function startClipFromUrl(formData: FormData) {
  if (!configured()) redirect('/?notice=configure-supabase');
  const workspaceId = String(formData.get('workspace_id') || '');
  const sourceUrl = String(formData.get('source_url') || '').trim();
  const targetClips = Number(formData.get('target_clips') || 4);
  const hookStyle = String(formData.get('hook_style') || 'pill');
  const captions = formData.get('captions') === 'on';
  const costReserve = Number(formData.get('estimated_cost_usd') || 0);
  if (!/^[0-9a-f-]{36}$/i.test(workspaceId)) redirect('/?notice=invalid-workspace#repurpose');
  if (formData.get('confirm_rights') !== 'on') redirect('/?notice=clip-rights#repurpose');
  let source: URL;
  try { source = new URL(sourceUrl); } catch { redirect('/?notice=clip-invalid-url#repurpose'); }
  const host = source.hostname.toLowerCase().replace(/^www\./, '').replace(/\.$/, '').replace(/^\[|\]$/g, '');
  const isYoutube = ['youtube.com', 'm.youtube.com', 'youtu.be'].includes(host);
  const isDirectVideo = /\.(mp4|mov|m4v|webm)(?:$|\/)/i.test(source.pathname);
  const isPrivateHost = isIP(host) !== 0 || ['localhost', 'localhost.localdomain'].includes(host) || /\.(local|localhost|internal|test)$/.test(host);
  if (source.protocol !== 'https:' || source.port || source.username || source.password || isPrivateHost || (!isYoutube && !isDirectVideo)) redirect('/?notice=clip-invalid-url#repurpose');
  if (!Number.isInteger(targetClips) || targetClips < 1 || targetClips > 15 || !['pill', 'classic', 'dark', 'yellow', 'red', 'outline', 'outline_yellow'].includes(hookStyle) || !Number.isFinite(costReserve) || costReserve < 0.01 || costReserve > 100) {
    redirect('/?notice=clip-invalid-options#repurpose');
  }
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY || !process.env.STUDIO_CREDENTIAL_ENCRYPTION_KEY) redirect('/?notice=engine-storage-unavailable#repurpose');

  const userClient = await createClient();
  const { data: claimsData } = await userClient.auth.getClaims();
  const userId = claimsData?.claims?.sub;
  if (!userId) redirect('/?notice=sign-in#repurpose');
  const { data: membership } = await userClient.from('workspace_members').select('role')
    .eq('workspace_id', workspaceId).eq('user_id', userId).maybeSingle();
  if (!membership || !['owner', 'admin', 'producer'].includes(membership.role)) redirect('/?notice=workspace-access#repurpose');

  let uncertainSubmission = false;
  try {
    const mcp = await studioMcpClient(workspaceId);
    const projectId = randomUUID();
    const title = `Clips from ${host}`.slice(0, 240);
    const factoryBrief = {
      idea: `Create ${targetClips} vertical clips from a video the creator has rights to use.`,
      pipeline: 'openshorts-clipping', source_url: sourceUrl, target_clips: targetClips,
      output_format: 'vertical', captions, auto_hook: captions, hook_style: hookStyle,
    };
    const operationsResponse = asRecord(await mcp.callTool('factory_operations', {
      capability: 'video_clipping', query: 'openshorts_process_video', include_schemas: true,
      check_health: true, offset: 0, limit: 100,
    }));
    const operationItems = Array.isArray(operationsResponse?.items) ? operationsResponse.items : [];
    const operation = operationItems.map(asRecord).find(item =>
      item?.native_tool === 'openshorts_process_video' || String(item?.operation || '').endsWith(':openshorts_process_video'),
    );
    if (!operation || typeof operation.operation !== 'string' || asRecord(operation.health)?.status !== 'available') {
      redirect('/?notice=clip-tool-unavailable#repurpose');
    }
    await mcp.callTool('factory_create_project', {
      project_id: projectId, title, pipeline: 'openshorts-clipping',
      config: { brief: factoryBrief, require_job_approval: true, max_job_estimate_usd: costReserve, max_project_estimate_usd: costReserve },
    });
    const approvalEvidence = 'Creator confirmed rights to process the source video and clicked Create vertical clips in Studio.';
    const briefArtifact = {
      version: '1.0', title, hook: 'Find the most compelling self-contained moments in the source.',
      key_points: ['Keep each clip faithful to the original context.', 'Favor a clear opening and a complete thought.'],
      tone: 'Clear, energetic, and faithful to the source.', style: `Vertical clips with ${hookStyle} hook treatment.`,
      target_platform: 'generic', target_duration_seconds: 45,
      target_audience: 'The original video audience', reference_material: [sourceUrl],
      metadata: { source_url: sourceUrl, rights_confirmed: true, target_clips: targetClips, output_format: 'vertical', captions, hook_style: hookStyle, estimated_cost_usd: costReserve },
    };
    await mcp.callTool('factory_checkpoint', {
      project_id: projectId, stage: 'idea', status: 'completed', artifacts: { brief: briefArtifact }, approval_evidence: approvalEvidence,
    });
    const requestHash = createHash('sha256').update(JSON.stringify({ projectId, sourceUrl, targetClips, hookStyle, captions, costReserve })).digest('hex').slice(0, 12);
    const planData = {
      request: `Studio clip from video ${requestHash}`,
      steps: [{
        id: 'studio_clip_source', stage: 'assets', operation: operation.operation,
        params: { source_url: sourceUrl, target_clips: targetClips, output_format: 'vertical', captions, auto_hook: captions, hook_style: hookStyle, confirm_rights: true, estimated_cost_usd: costReserve },
        depends_on: [], reason: 'Creator requested vertical short clips, confirmed rights, and approved the displayed cost reserve.',
      }],
      alternatives: [],
    };
    const preflight = asRecord(await mcp.callTool('factory_preflight_route', { project_id: projectId, plan: planData }));
    if (preflight?.ready_to_save !== true) redirect('/?notice=clip-preflight-failed#repurpose');
    const steps = Array.isArray(asRecord(preflight.preflight)?.steps) ? asRecord(preflight.preflight)?.steps as unknown[] : [];
    const preflightStep = asRecord(steps[0]);
    const preflightEstimate = Number(preflightStep?.estimated_cost_usd);
    if (!Number.isFinite(preflightEstimate) || preflightEstimate < 0 || preflightEstimate > costReserve) redirect('/?notice=clip-budget-exceeded#repurpose');
    const saved = asRecord(await mcp.callTool('factory_save_route', { project_id: projectId, plan: planData }));
    if (typeof saved?.plan_id !== 'string') redirect('/?notice=clip-preflight-failed#repurpose');

    const { error: insertError } = await userClient.from('projects').insert({
      id: projectId, workspace_id: workspaceId, created_by: userId, title,
      platform: 'multi', format: 'vertical', status: 'in_progress',
      brief: { version: 1, ...factoryBrief, status: 'clip_processing', estimated_cost_usd: costReserve },
    });
    if (insertError) redirect('/?notice=clip-save-failed#repurpose');

    uncertainSubmission = true;
    const submitted = asRecord(await mcp.callTool('factory_submit_job', {
      project_id: projectId, plan_id: saved.plan_id, step_id: 'studio_clip_source',
      idempotency_key: `studio_clips_${projectId.replaceAll('-', '')}_${requestHash}`,
      approval_evidence: `${approvalEvidence} Cost preflight passed with a USD ${costReserve.toFixed(2)} reserve.`,
    }));
    if (!submitted || typeof submitted.job_id !== 'string') redirect('/?notice=clip-submission-unknown#projects');
    await userClient.from('projects').update({ brief: { version: 1, ...factoryBrief, status: 'clip_processing', estimated_cost_usd: costReserve, job_id: submitted.job_id } })
      .eq('workspace_id', workspaceId).eq('id', projectId);
    revalidatePath('/');
    redirect('/?notice=clips-started#projects');
  } catch (error) {
    if (error instanceof Error && error.message.includes('NEXT_REDIRECT')) throw error;
    redirect(uncertainSubmission ? '/?notice=clip-submission-unknown#projects' : '/?notice=clip-start-failed#repurpose');
  }
}

export type ClipRefreshState = { message?: string; error?: string; clips?: Array<{ title: string; url: string }> };

function decodeMcpPayload(value: unknown): unknown {
  if (typeof value === 'string') {
    try { return decodeMcpPayload(JSON.parse(value)); } catch { return value; }
  }
  if (Array.isArray(value)) return value.map(decodeMcpPayload);
  const record = asRecord(value);
  if (!record) return value;
  return Object.fromEntries(Object.entries(record).map(([key, item]) => [key, decodeMcpPayload(item)]));
}

function findValueByKey(value: unknown, keys: string[], predicate: (item: unknown) => boolean): unknown {
  if (Array.isArray(value)) {
    for (const item of value) { const found = findValueByKey(item, keys, predicate); if (found !== undefined) return found; }
  } else {
    const record = asRecord(value);
    if (record) {
      for (const key of keys) if (key in record && predicate(record[key])) return record[key];
      for (const item of Object.values(record)) { const found = findValueByKey(item, keys, predicate); if (found !== undefined) return found; }
    }
  }
  return undefined;
}

function findClipLinks(value: unknown): Array<{ title: string; url: string }> {
  const payload = decodeMcpPayload(value);
  let rawClips: unknown;
  const visit = (item: unknown): boolean => {
    if (Array.isArray(item)) return item.some(visit);
    const record = asRecord(item);
    if (!record) return false;
    if (Array.isArray(record.clips)) { rawClips = record.clips; return true; }
    return Object.values(record).some(visit);
  };
  visit(payload);
  const urls: Array<{ title: string; url: string }> = [];
  const entries = Array.isArray(rawClips) ? rawClips : [];
  for (const item of entries) {
    const clip = asRecord(item);
    if (!clip) continue;
    const candidate = ['download_url', 'clip_url', 'video_url', 'url'].map(key => clip[key]).find(url => typeof url === 'string');
    if (typeof candidate !== 'string') continue;
    try {
      const link = new URL(candidate);
      if (link.protocol === 'https:' && !link.username && !link.password) urls.push({ title: String(clip.title || clip.name || `Clip ${urls.length + 1}`).slice(0, 120), url: link.toString() });
    } catch { /* Ignore non-URL or local file results. */ }
  }
  return urls.slice(0, 15);
}

export async function refreshStudioClips(_previous: ClipRefreshState, formData: FormData): Promise<ClipRefreshState> {
  const workspaceId = String(formData.get('workspace_id') || '');
  const projectId = String(formData.get('project_id') || '');
  if (!/^[0-9a-f-]{36}$/i.test(workspaceId) || !/^[0-9a-f-]{36}$/i.test(projectId)) return { error: 'Refresh the workspace and choose a valid clip project.' };
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY || !process.env.STUDIO_CREDENTIAL_ENCRYPTION_KEY) return { error: 'Secure Studio engine access is not configured.' };
  const userClient = await createClient();
  const { data: claimsData } = await userClient.auth.getClaims();
  const userId = claimsData?.claims?.sub;
  if (!userId) return { error: 'Sign in again before checking clip progress.' };
  const { data: membership } = await userClient.from('workspace_members').select('role')
    .eq('workspace_id', workspaceId).eq('user_id', userId).maybeSingle();
  if (!membership || !['owner', 'admin', 'producer', 'reviewer'].includes(membership.role)) return { error: 'You do not have access to this clip project.' };
  const { data: project } = await userClient.from('projects').select('brief,status').eq('workspace_id', workspaceId).eq('id', projectId).maybeSingle();
  const brief = asRecord(project?.brief) || {};
  if (brief.pipeline !== 'openshorts-clipping' || typeof brief.job_id !== 'string') return { error: 'This project does not have a clip job to check.' };
  try {
    const mcp = await studioMcpClient(workspaceId);
    const factoryJob = asRecord(decodeMcpPayload(await mcp.callTool('factory_job_status', { project_id: projectId, job_id: brief.job_id })));
    const factoryStatus = String(factoryJob?.status || 'unknown').toLowerCase();
    if (factoryStatus !== 'completed') {
      const message = factoryStatus === 'failed' ? 'The MCP clip request failed. Check project activity for details.' : `Clip request ${factoryStatus}. Check again after the engine finishes submitting it.`;
      return { message };
    }
    const upstreamJobId = findValueByKey(factoryJob?.result, ['job_id'], item => typeof item === 'string' && item !== brief.job_id) as string | undefined;
    if (!upstreamJobId) return { message: 'OpenShorts has not returned its processing job ID yet. Check again shortly.' };
    const statusPayload = decodeMcpPayload(await mcp.callTool('openshorts_get_job_status', { job_id: upstreamJobId }));
    const upstreamStatus = String(findValueByKey(statusPayload, ['status', 'job_status'], item => typeof item === 'string') || 'unknown').toLowerCase();
    const nextBrief = { ...brief, clip_upstream_job_id: upstreamJobId, clip_status: upstreamStatus };
    if (!['completed', 'complete', 'succeeded', 'success'].includes(upstreamStatus)) {
      await userClient.from('projects').update({ brief: nextBrief }).eq('workspace_id', workspaceId).eq('id', projectId);
      revalidatePath('/');
      return { message: ['failed', 'error'].includes(upstreamStatus) ? `OpenShorts reports ${upstreamStatus}. Review the job before retrying.` : `OpenShorts is ${upstreamStatus}; clips are still processing.` };
    }
    const clipPayload = await mcp.callTool('openshorts_list_clips', { job_id: upstreamJobId });
    const clips = findClipLinks(clipPayload);
    const completedBrief = { ...nextBrief, clip_status: 'completed', clip_outputs: clips };
    await userClient.from('projects').update({ status: clips.length ? 'review' : project?.status || 'in_progress', brief: completedBrief })
      .eq('workspace_id', workspaceId).eq('id', projectId);
    revalidatePath('/');
    return clips.length ? { message: `${clips.length} clips are ready for review.`, clips } : { message: 'OpenShorts finished, but Studio could not find download links in the response. Check the MCP project output.' };
  } catch (error) {
    return { error: `Could not refresh clip results: ${(error instanceof Error ? error.message : 'MCP error').slice(0, 260)}` };
  }
}

export type StartResearchState = { submitted?: string; error?: string };

export async function startStudioResearch(_previous: StartResearchState, formData: FormData): Promise<StartResearchState> {
  if (!configured()) return { error: 'Connect Supabase before starting research.' };
  const workspaceId = String(formData.get('workspace_id') || '');
  const projectId = String(formData.get('project_id') || '');
  if (!/^[0-9a-f-]{36}$/i.test(workspaceId) || !/^[0-9a-f-]{36}$/i.test(projectId)) return { error: 'Refresh the workspace and choose a valid project.' };
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY || !process.env.STUDIO_CREDENTIAL_ENCRYPTION_KEY) {
    return { error: 'Secure Studio engine access is not configured on this server.' };
  }

  const userClient = await createClient();
  const { data: claimsData } = await userClient.auth.getClaims();
  const userId = claimsData?.claims?.sub;
  if (!userId) return { error: 'Sign in again before starting research.' };
  const { data: membership } = await userClient.from('workspace_members').select('role')
    .eq('workspace_id', workspaceId).eq('user_id', userId).maybeSingle();
  if (!membership || !['owner', 'admin', 'producer'].includes(membership.role)) {
    return { error: 'You need producer access to start project research.' };
  }
  const { data: project, error: projectError } = await userClient.from('projects')
    .select('id,title,platform,format,status,brief').eq('workspace_id', workspaceId).eq('id', projectId).maybeSingle();
  if (projectError || !project) return { error: 'That project is not available in this workspace.' };
  const brief = asRecord(project.brief) || {};
  if (brief.research_freshness !== 'evergreen') {
    return { error: 'Live and recent research is not enabled for this engine yet. Choose “Evergreen background” for the free, cited source search.' };
  }
  if (!['brief', 'research'].includes(project.status)) return { error: 'Research can only start from a saved brief. Review the current project state first.' };

  try {
    const mcp = await studioMcpClient(workspaceId);
    const pipeline = typeof brief.pipeline === 'string' ? brief.pipeline : '';
    if (!pipeline) return { error: 'This project brief is missing its production pipeline. Save a new brief and try again.' };
    const factoryBrief = {
      idea: typeof brief.idea === 'string' ? brief.idea : project.title,
      audience: brief.audience || '',
      goal: brief.goal || '',
      region: brief.region || '',
      research_freshness: brief.research_freshness,
      platform: brief.platform || project.platform,
      format: brief.format || project.format,
      duration_seconds: brief.duration_seconds || [],
      visual_style: brief.visual_style || null,
      brand_profile: brief.brand_profile || null,
    };

    let projectExists = false;
    for (let offset = 0; offset <= 4_900; offset += 100) {
      const listing = asRecord(await mcp.callTool('factory_projects', { offset, limit: 100 }));
      const items = Array.isArray(listing?.items) ? listing.items : [];
      if (items.some(item => asRecord(item)?.project_id === projectId)) {
        projectExists = true;
        break;
      }
      if (typeof listing?.next_offset !== 'number') break;
    }
    if (!projectExists) {
      await mcp.callTool('factory_create_project', {
        project_id: projectId,
        title: project.title,
        pipeline,
        config: { brief: factoryBrief, require_job_approval: true },
      });
    }

    const queryTerms = [factoryBrief.idea, factoryBrief.audience, factoryBrief.region]
      .filter(value => typeof value === 'string' && value.trim()).join(' ');
    const query = queryTerms.slice(0, 500);
    const briefFingerprint = createHash('sha256').update(JSON.stringify({ projectId, factoryBrief, query })).digest('hex').slice(0, 12);
    const routeRequest = `OpenMontage Studio research ${briefFingerprint}`;
    const routeList = asRecord(await mcp.callTool('factory_routes', { project_id: projectId, offset: 0, limit: 100 }));
    const existing = (Array.isArray(routeList?.items) ? routeList.items : [])
      .map(asRecord).find(item => item?.request === routeRequest);

    let plan: Record<string, unknown>;
    if (existing && typeof existing.plan_id === 'string') {
      const saved = asRecord(await mcp.callTool('factory_routes', { project_id: projectId, plan_id: existing.plan_id }));
      const steps = Array.isArray(saved?.steps) ? saved.steps : [];
      const savedStep = steps.map(asRecord).find(step => step?.id === 'studio_research_search');
      const savedParams = asRecord(savedStep?.params);
      if (!savedStep || typeof savedStep.operation !== 'string' || !savedStep.operation.endsWith(':research_search')
        || savedParams?.provider !== 'wikipedia' || savedParams.limit !== 5
        || Number(savedStep.estimated_cost_usd) !== 0) {
        return { error: 'The saved research route is incomplete. Inspect the route in an MCP client before retrying.' };
      }
      // factory_routes(plan_id=...) returns the stored plan body, not the
      // submit envelope; preserve the id from the paginated route listing.
      plan = { project_id: projectId, plan_id: existing.plan_id, step_id: 'studio_research_search' };
    } else {
      const operationsResponse = asRecord(await mcp.callTool('factory_operations', {
        capability: 'research', query: 'research_search', include_schemas: true, check_health: true, offset: 0, limit: 100,
      }));
      const operationItems = Array.isArray(operationsResponse?.items) ? operationsResponse.items : [];
      const operation = operationItems.map(asRecord).find(item =>
        item?.native_tool === 'research_search' || String(item?.operation || '').endsWith(':research_search'),
      );
      if (!operation || typeof operation.operation !== 'string' || asRecord(operation.health)?.status !== 'available') {
        return { error: 'The connected MCP does not currently report an available research_search operation.' };
      }
      const planData = {
        request: routeRequest,
        steps: [{
          id: 'studio_research_search',
          stage: 'research',
          operation: operation.operation,
          params: { query, provider: 'wikipedia', limit: 5 },
          depends_on: [],
          reason: 'Find free background source leads for the approved brief. Search snippets are discovery leads and are not verified evidence.',
        }],
        alternatives: [],
      };
      const preflight = asRecord(await mcp.callTool('factory_preflight_route', { project_id: projectId, plan: planData }));
      if (preflight?.ready_to_submit !== false || preflight.ready_to_save !== true) {
        return { error: 'The engine did not confirm a no-cost research preflight. No research job was submitted.' };
      }
      const details = asRecord(preflight.preflight);
      const resolvedSteps = Array.isArray(details?.steps) ? details.steps : [];
      const estimate = Number(asRecord(resolvedSteps[0])?.estimated_cost_usd);
      if (!Number.isFinite(estimate) || estimate !== 0) {
        return { error: 'The research search is not free on this engine, so Studio stopped before submitting it.' };
      }
      const saved = asRecord(await mcp.callTool('factory_save_route', { project_id: projectId, plan: planData }));
      if (typeof saved?.plan_id !== 'string') return { error: 'The research route was validated but the engine did not save it.' };
      plan = { project_id: projectId, plan_id: saved.plan_id, step_id: 'studio_research_search' };
    }

    const planId = typeof plan.plan_id === 'string' ? plan.plan_id : '';
    const stepId = typeof plan.step_id === 'string' ? plan.step_id : 'studio_research_search';
    if (!planId) return { error: 'The saved research route is missing its plan identifier.' };
    const idempotencyKey = `studio_research_${projectId.replaceAll('-', '')}_${briefFingerprint}`;
    const submitted = asRecord(await mcp.callTool('factory_submit_job', {
      project_id: projectId,
      plan_id: planId,
      step_id: stepId,
      idempotency_key: idempotencyKey,
      approval_evidence: 'Creator clicked “Start free research” in OpenMontage Studio. Preflight confirmed a $0.00 Wikipedia source search.',
    }));
    if (!submitted || typeof submitted.job_id !== 'string') return { error: 'The engine did not return a job identifier. Check the MCP project before retrying.' };

    const nextBrief = { ...brief, status: 'research_in_progress', research_job_id: submitted.job_id };
    await userClient.from('projects').update({ status: 'research', brief: nextBrief })
      .eq('workspace_id', workspaceId).eq('id', projectId).in('status', ['brief', 'research']);
    revalidatePath('/');
    return { submitted: `Research ${submitted.status === 'completed' ? 'already completed' : 'started'} · $0.00 · job ${submitted.job_id.slice(0, 8)}` };
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unexpected MCP error';
    return { error: `Research did not start: ${message.slice(0, 360)}` };
  }
}

export type ResearchResultState = {
  query?: string;
  leads?: Array<{ title: string; url: string; snippet: string }>;
  message?: string;
  error?: string;
};

function plainResearchText(value: unknown, maximum: number): string {
  if (typeof value !== 'string') return '';
  return value.replace(/<[^>]*>/g, ' ')
    .replace(/&amp;/gi, '&').replace(/&quot;/gi, '"').replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, '<').replace(/&gt;/gi, '>')
    .replace(/\s+/g, ' ').trim().slice(0, maximum);
}

export async function loadStudioResearchResult(_previous: ResearchResultState, formData: FormData): Promise<ResearchResultState> {
  if (!configured()) return { error: 'Studio is not connected to its workspace database.' };
  const workspaceId = String(formData.get('workspace_id') || '');
  const projectId = String(formData.get('project_id') || '');
  if (!/^[0-9a-f-]{36}$/i.test(workspaceId) || !/^[0-9a-f-]{36}$/i.test(projectId)) {
    return { error: 'Refresh Studio and choose a valid project.' };
  }

  try {
    const userClient = await createClient();
    const { data: claimsData } = await userClient.auth.getClaims();
    const userId = claimsData?.claims?.sub;
    if (!userId) return { error: 'Sign in again before viewing research.' };
    const { data: membership } = await userClient.from('workspace_members').select('role')
      .eq('workspace_id', workspaceId).eq('user_id', userId).maybeSingle();
    if (!membership) return { error: 'You do not have access to this workspace.' };
    const { data: project, error: projectError } = await userClient.from('projects')
      .select('id,status,brief').eq('workspace_id', workspaceId).eq('id', projectId).maybeSingle();
    if (projectError || !project) return { error: 'That project is not available in this workspace.' };
    const brief = asRecord(project.brief) || {};
    const jobId = typeof brief.research_job_id === 'string' ? brief.research_job_id : '';
    if (!/^[0-9a-f]{32}$/i.test(jobId) || brief.research_freshness !== 'evergreen') {
      return { error: 'This project has no supported Studio research result to review.' };
    }
    const { data: job, error: jobError } = await userClient.from('jobs')
      .select('id,operation,status').eq('id', jobId).eq('workspace_id', workspaceId)
      .eq('project_id', projectId).maybeSingle();
    if (jobError || !job || !String(job.operation).endsWith(':research_search')) {
      return { message: 'The research job is not visible yet. Wait a few seconds and check again.' };
    }
    if (job.status !== 'succeeded') {
      if (['queued', 'running'].includes(job.status)) return { message: 'Research is still running. Check again shortly.' };
      return { error: `The research job is ${String(job.status).replaceAll('_', ' ')}. Review production activity for details; Studio will not retry it automatically.` };
    }

    const mcp = await studioMcpClient(workspaceId);
    const jobResult = asRecord(await mcp.callTool('factory_job_status', {
      project_id: projectId, job_id: jobId, log_tail_bytes: 0,
    }));
    if (jobResult?.status !== 'completed') return { message: 'The engine has not marked this research run complete yet. Check again shortly.' };
    const output = asRecord(jobResult.result);
    const data = asRecord(output?.data);
    if (output?.success !== true || !data || !Array.isArray(data.results)) {
      return { error: 'The completed job did not contain a supported source-search result.' };
    }
    const leads = data.results.slice(0, 5).flatMap((raw) => {
      const item = asRecord(raw);
      if (!item) return [];
      const title = plainResearchText(item.title, 240);
      const snippet = plainResearchText(item.snippet, 800);
      let url = '';
      try {
        const parsed = new URL(String(item.url || ''));
        if (parsed.protocol === 'https:' && !parsed.username && !parsed.password) url = parsed.toString();
      } catch { /* Exclude malformed or unsafe source links. */ }
      return title && url ? [{ title, url, snippet }] : [];
    });
    return {
      query: plainResearchText(data.query, 500),
      leads,
      message: leads.length ? undefined : 'The search completed, but it returned no safe source links to show.',
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unexpected research review error';
    return { error: `Could not load source leads: ${message.slice(0, 240)}` };
  }
}

export type StudioRenderState = {
  render?: { filename: string; url: string; bytes: number; expiresInSeconds: number };
  message?: string;
  error?: string;
};

export async function loadStudioRender(_previous: StudioRenderState, formData: FormData): Promise<StudioRenderState> {
  if (!configured()) return { error: 'Studio is not connected to its workspace database.' };
  const workspaceId = String(formData.get('workspace_id') || '');
  const projectId = String(formData.get('project_id') || '');
  if (!/^[0-9a-f-]{36}$/i.test(workspaceId) || !/^[0-9a-f-]{36}$/i.test(projectId)) {
    return { error: 'Refresh Studio and choose a valid project.' };
  }
  try {
    const userClient = await createClient();
    const { data: claimsData } = await userClient.auth.getClaims();
    const userId = claimsData?.claims?.sub;
    if (!userId) return { error: 'Sign in again before opening this render.' };
    const { data: membership } = await userClient.from('workspace_members').select('role')
      .eq('workspace_id', workspaceId).eq('user_id', userId).maybeSingle();
    if (!membership) return { error: 'You do not have access to this workspace.' };
    const { data: project, error: projectError } = await userClient.from('projects')
      .select('id,status').eq('workspace_id', workspaceId).eq('id', projectId).maybeSingle();
    if (projectError || !project) return { error: 'That project is not available in this workspace.' };
    const mcp = await studioMcpClient(workspaceId);
    const output = asRecord(await mcp.callTool('factory_outputs', { project_id: projectId, offset: 0, limit: 100 }));
    const items = Array.isArray(output?.items) ? output.items : [];
    const marker = `/${projectId}/renders/`;
    const candidate = items.map(asRecord).find((item) => {
      if (!item || typeof item.path !== 'string') return false;
      const path = item.path;
      const markerIndex = path.lastIndexOf(marker);
      if (markerIndex < 0 || !/\.(mp4|mov|webm)$/i.test(path)) return false;
      const relative = `renders/${path.slice(markerIndex + marker.length)}`;
      const segments = relative.split('/');
      return relative.length <= 512 && segments.every(segment => Boolean(segment) && segment !== '.' && segment !== '..' && /^[a-zA-Z0-9_. ()-]+$/.test(segment));
    });
    if (!candidate || typeof candidate.path !== 'string') return { message: 'No finished video render is available in this project yet.' };
    const markerIndex = candidate.path.lastIndexOf(marker);
    const relativePath = `renders/${candidate.path.slice(markerIndex + marker.length)}`;
    const media = asRecord(await mcp.callTool('factory_export_media', {
      project_id: projectId, relative_path: relativePath, mode: 'link',
    }));
    if (typeof media?.download_url !== 'string') {
      return { error: 'The connected MCP host does not have signed browser media delivery configured yet.' };
    }
    const link = new URL(media.download_url);
    const expectedEndpoint = new URL(process.env.NEXT_PUBLIC_MCP_ENDPOINT || '');
    if (link.protocol !== 'https:' || link.origin !== expectedEndpoint.origin || link.username || link.password) {
      return { error: 'The render link did not match the configured secure MCP host.' };
    }
    return {
      render: {
        filename: typeof media.filename === 'string' ? media.filename.slice(0, 240) : 'render.mp4',
        url: link.toString(),
        bytes: Number.isSafeInteger(media.bytes) && Number(media.bytes) >= 0 ? Number(media.bytes) : 0,
        expiresInSeconds: Number.isSafeInteger(media.expires_in_seconds) ? Number(media.expires_in_seconds) : 300,
      },
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unexpected media export error';
    return { error: `Could not open this render: ${message.slice(0, 240)}` };
  }
}

export async function saveBrandProfile(formData: FormData) {
  if (!configured()) redirect('/?notice=configure-supabase');
  const workspaceId = String(formData.get('workspace_id') || '');
  const brandName = String(formData.get('brand_name') || '').trim();
  const audience = String(formData.get('brand_audience') || '').trim();
  const voice = String(formData.get('brand_voice') || '').trim();
  const visualDirection = String(formData.get('visual_direction') || '').trim();
  const avoidTermsRaw = String(formData.get('avoid_terms') || '');
  const colorPalette = String(formData.get('color_palette') || '').trim();
  const avoidTerms = [...new Set(avoidTermsRaw.split(/[\n,]/).map(term => term.trim()).filter(Boolean))];
  if (!/^[0-9a-f-]{36}$/i.test(workspaceId) || brandName.length < 1 || brandName.length > 120
    || audience.length > 500 || voice.length > 2000 || visualDirection.length > 2000
    || avoidTerms.length > 40 || avoidTerms.some(term => term.length > 80) || colorPalette.length > 240) {
    redirect('/?notice=invalid-brand-profile#brand');
  }
  const supabase = await createClient();
  const { data: claimsData } = await supabase.auth.getClaims();
  const userId = claimsData?.claims?.sub;
  if (!userId) redirect('/?notice=sign-in');
  const { data: membership } = await supabase.from('workspace_members').select('role')
    .eq('workspace_id', workspaceId).eq('user_id', userId).maybeSingle();
  if (!membership || !['owner', 'admin'].includes(membership.role)) redirect('/?notice=brand-admin-required#brand');
  const { error } = await supabase.from('workspace_brand_profiles').upsert({
    workspace_id: workspaceId,
    brand_name: brandName,
    audience,
    voice,
    visual_direction: visualDirection,
    avoid_terms: avoidTerms,
    color_palette: colorPalette,
    updated_by: userId,
    updated_at: new Date().toISOString(),
  }, { onConflict: 'workspace_id' });
  if (error) redirect('/?notice=brand-save-failed#brand');
  revalidatePath('/');
  redirect('/?notice=brand-saved#brand');
}

export type EngineConnectionActionState = { connected?: string; error?: string };

export async function connectStudioEngine(_previous: EngineConnectionActionState, formData: FormData): Promise<EngineConnectionActionState> {
  if (!configured()) return { error: 'Connect Supabase before connecting an engine.' };
  const workspaceId = String(formData.get('workspace_id') || '');
  const label = String(formData.get('label') || '').trim();
  const endpoint = process.env.NEXT_PUBLIC_MCP_ENDPOINT || '';
  if (!/^[0-9a-f-]{36}$/i.test(workspaceId) || !label || label.length > 120) return { error: 'Enter an engine label up to 120 characters.' };
  if (!endpoint) return { error: 'Set NEXT_PUBLIC_MCP_ENDPOINT in the Studio server environment, then reconnect.' };
  try {
    const parsedEndpoint = new URL(endpoint);
    const secure = parsedEndpoint.protocol === 'https:' || (parsedEndpoint.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(parsedEndpoint.hostname));
    if (!secure || parsedEndpoint.username || parsedEndpoint.password || parsedEndpoint.search || parsedEndpoint.hash) {
      return { error: 'Configure an HTTPS MCP URL without credentials or query parameters. HTTP is allowed only for localhost development.' };
    }
  } catch {
    return { error: 'Set NEXT_PUBLIC_MCP_ENDPOINT to a valid MCP URL before connecting.' };
  }
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY || !process.env.STUDIO_CREDENTIAL_ENCRYPTION_KEY) {
    return { error: 'Secure engine connection storage is not configured on this Studio server.' };
  }

  const userClient = await createClient();
  const { data: claimsData } = await userClient.auth.getClaims();
  const userId = claimsData?.claims?.sub;
  if (!userId) return { error: 'Sign in again to connect an engine.' };
  const { data: membership } = await userClient.from('workspace_members').select('role')
    .eq('workspace_id', workspaceId).eq('user_id', userId).maybeSingle();
  if (!membership || !['owner', 'admin'].includes(membership.role)) {
    return { error: 'Only workspace owners and admins can connect an engine.' };
  }

  let encrypted;
  try {
    const token = `om_live_${randomBytes(32).toString('base64url')}`;
    const tokenHash = createHash('sha256').update(token, 'utf8').digest('hex');
    encrypted = encryptCredential(token);
    const admin = createServiceClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY, {
      auth: { autoRefreshToken: false, persistSession: false, detectSessionInUrl: false },
    });
    const { data: connectionId, error } = await admin.rpc('store_studio_engine_connection', {
      target_workspace_id: workspaceId,
      target_label: label,
      target_endpoint_url: endpoint,
      actor_id: userId,
      presented_hash: `\\x${tokenHash}`,
      token_expires_at: new Date(Date.now() + 365 * 24 * 60 * 60 * 1000).toISOString(),
      encrypted_payload: `\\x${encrypted.ciphertext.toString('hex')}`,
      encryption_version: encrypted.keyVersion,
    });
    if (error || typeof connectionId !== 'string') return { error: 'Studio could not store the encrypted engine connection. Apply the latest Supabase migration and try again.' };

    let tools;
    try {
      tools = await listMcpTools(endpoint, token);
    } catch {
      await admin.rpc('mark_studio_engine_offline', { target_connection_id: connectionId });
      revalidatePath('/');
      return { error: 'Studio saved the connection, but could not complete the MCP handshake. Check the configured endpoint and server availability.' };
    }
    let schemaBudget = 500_000;
    const capabilities = tools.map(tool => {
      let schema: Record<string, unknown> = {};
      if (tool.inputSchema) {
        const serialized = JSON.stringify(tool.inputSchema);
        if (serialized.length <= Math.min(8000, schemaBudget)) {
          schema = tool.inputSchema;
          schemaBudget -= serialized.length;
        }
      }
      return {
        operation_key: tool.name,
        display_name: tool.name.replace(/^factory_/, '').replaceAll('_', ' '),
        description: (tool.description || '').slice(0, 600),
        pipeline_stage: capabilityStage(tool.name),
        input_schema: schema,
      };
    });
    const { error: syncError } = await admin.rpc('sync_studio_engine_capabilities', {
      target_connection_id: connectionId,
      target_capabilities: capabilities,
    });
    if (syncError) {
      await admin.rpc('mark_studio_engine_offline', { target_connection_id: connectionId });
      revalidatePath('/');
      return { error: 'The MCP responded, but Studio could not save its tool catalog. Check the latest Supabase migration.' };
    }
    const { data: olderConnections } = await admin.from('engine_connections').select('mcp_token_id')
      .eq('workspace_id', workspaceId).eq('label', label).neq('id', connectionId).neq('status', 'revoked');
    let oldTokenCleanupFailed = false;
    for (const oldConnection of olderConnections || []) {
      if (!oldConnection.mcp_token_id) continue;
      const { error: revokeError } = await admin.rpc('revoke_workspace_mcp_token', {
        target_workspace_id: workspaceId,
        target_token_id: oldConnection.mcp_token_id,
        actor_id: userId,
      });
      if (revokeError) oldTokenCleanupFailed = true;
    }
    revalidatePath('/');
    return { connected: `Connected. Studio discovered ${tools.length} MCP tools.${oldTokenCleanupFailed ? ' A previous token could not be retired; disconnect its old connection below.' : ''}` };
  } catch {
    return { error: 'Studio could not establish a secure engine connection. Check its server configuration and try again.' };
  }
}

export async function revokeStudioEngineConnection(formData: FormData) {
  if (!configured()) redirect('/?notice=configure-supabase');
  const workspaceId = String(formData.get('workspace_id') || '');
  const connectionId = String(formData.get('connection_id') || '');
  if (!/^[0-9a-f-]{36}$/i.test(workspaceId) || !/^[0-9a-f-]{36}$/i.test(connectionId)) redirect('/?notice=invalid-workspace#engine');
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY) redirect('/?notice=engine-storage-unavailable#engine');
  const userClient = await createClient();
  const { data: claimsData } = await userClient.auth.getClaims();
  const userId = claimsData?.claims?.sub;
  if (!userId) redirect('/?notice=sign-in');
  const { data: membership } = await userClient.from('workspace_members').select('role')
    .eq('workspace_id', workspaceId).eq('user_id', userId).maybeSingle();
  if (!membership || !['owner', 'admin'].includes(membership.role)) redirect('/?notice=engine-admin-required#engine');
  const admin = createServiceClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false, detectSessionInUrl: false },
  });
  const { data: connection } = await admin.from('engine_connections').select('mcp_token_id')
    .eq('workspace_id', workspaceId).eq('id', connectionId).maybeSingle();
  if (!connection?.mcp_token_id) redirect('/?notice=engine-not-found#engine');
  const { data: revoked, error } = await admin.rpc('revoke_workspace_mcp_token', {
    target_workspace_id: workspaceId,
    target_token_id: connection.mcp_token_id,
    actor_id: userId,
  });
  if (error) redirect('/?notice=engine-revoke-failed#engine');
  if (!revoked) redirect('/?notice=engine-already-revoked#engine');
  revalidatePath('/');
  redirect('/?notice=engine-revoked#engine');
}

export async function saveProviderCredential(formData: FormData) {
  if (!configured()) redirect('/?notice=configure-supabase');
  const workspaceId = String(formData.get('workspace_id') || '');
  const provider = String(formData.get('provider') || '').trim().toLowerCase();
  const label = String(formData.get('label') || '').trim();
  const apiKey = String(formData.get('api_key') || '').trim();
  if (!/^[0-9a-f-]{36}$/i.test(workspaceId)) redirect('/?notice=invalid-workspace');
  if (!/^[a-z][a-z0-9._-]{1,63}$/.test(provider) || !label || label.length > 120 || apiKey.length < 8 || apiKey.length > 4096) {
    redirect('/?notice=invalid-provider-credential');
  }
  let credentialValue = apiKey;
  if (apiKey.startsWith('{')) {
    try {
      const parsed: unknown = JSON.parse(apiKey);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('expected an object');
      const entries = Object.entries(parsed);
      if ((parsed as Record<string, unknown>).type === 'service_account') {
        const account = parsed as Record<string, unknown>;
        const requiredFields = ['project_id', 'private_key_id', 'private_key', 'client_email', 'client_id', 'auth_uri', 'token_uri'];
        if (provider !== 'google' || requiredFields.some(name => typeof account[name] !== 'string' || !String(account[name]).trim())) {
          throw new Error('invalid Google service-account JSON');
        }
        if (!String(account.private_key).includes('-----BEGIN PRIVATE KEY-----') || !String(account.client_email).endsWith('.iam.gserviceaccount.com')) {
          throw new Error('invalid Google service-account key');
        }
        const allowedFields = new Set([...requiredFields, 'type', 'auth_provider_x509_cert_url', 'client_x509_cert_url', 'universe_domain']);
        if (entries.some(([name]) => !allowedFields.has(name))) throw new Error('unexpected Google service-account field');
        credentialValue = JSON.stringify(parsed);
      } else {
        if (!entries.length || entries.some(([name, value]) => !/^[A-Z][A-Z0-9_]{1,127}$/.test(name) || typeof value !== 'string' || !value.trim())) {
          throw new Error('invalid credential map');
        }
        credentialValue = JSON.stringify(Object.fromEntries(entries.sort(([a], [b]) => a.localeCompare(b))));
      }
      if (credentialValue.length > 4096) throw new Error('credential map is too large');
    } catch {
      redirect('/?notice=invalid-provider-credential');
    }
  }
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY || !process.env.STUDIO_CREDENTIAL_ENCRYPTION_KEY) {
    redirect('/?notice=credential-storage-unavailable');
  }

  const userClient = await createClient();
  const { data: claimsData } = await userClient.auth.getClaims();
  const userId = claimsData?.claims?.sub;
  if (!userId) redirect('/?notice=sign-in');
  const { data: membership } = await userClient.from('workspace_members').select('role')
    .eq('workspace_id', workspaceId).eq('user_id', userId).maybeSingle();
  if (!membership || !['owner', 'admin'].includes(membership.role)) redirect('/?notice=provider-admin-required');

  const encrypted = encryptCredential(credentialValue);
  const admin = createServiceClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false, detectSessionInUrl: false },
  });
  const { error } = await admin.rpc('store_provider_credential', {
    target_workspace_id: workspaceId,
    target_provider: provider,
    target_label: label,
    safe_hint: apiKey.startsWith('{') ? 'structured credential' : `••••${apiKey.slice(-4)}`,
    actor_id: userId,
    encrypted_payload: `\\x${encrypted.ciphertext.toString('hex')}`,
    encryption_version: encrypted.keyVersion,
  });
  if (error) redirect(error.code === '23505' ? '/?notice=provider-label-taken#providers' : '/?notice=provider-save-failed#providers');
  revalidatePath('/');
  redirect('/?notice=provider-saved#providers');
}

export async function revokeProviderCredential(formData: FormData) {
  if (!configured()) redirect('/?notice=configure-supabase');
  const workspaceId = String(formData.get('workspace_id') || '');
  const connectionId = String(formData.get('connection_id') || '');
  if (!/^[0-9a-f-]{36}$/i.test(workspaceId) || !/^[0-9a-f-]{36}$/i.test(connectionId)) {
    redirect('/?notice=invalid-workspace');
  }
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY) redirect('/?notice=credential-storage-unavailable');

  const userClient = await createClient();
  const { data: claimsData } = await userClient.auth.getClaims();
  const userId = claimsData?.claims?.sub;
  if (!userId) redirect('/?notice=sign-in');
  const { data: membership } = await userClient.from('workspace_members').select('role')
    .eq('workspace_id', workspaceId).eq('user_id', userId).maybeSingle();
  if (!membership || !['owner', 'admin'].includes(membership.role)) redirect('/?notice=provider-admin-required');

  const admin = createServiceClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false, detectSessionInUrl: false },
  });
  const { data: revoked, error } = await admin.rpc('revoke_provider_credential', {
    target_workspace_id: workspaceId,
    target_connection_id: connectionId,
    actor_id: userId,
  });
  if (error) redirect('/?notice=provider-revoke-failed#providers');
  if (!revoked) redirect('/?notice=provider-already-revoked#providers');
  revalidatePath('/');
  redirect('/?notice=provider-revoked#providers');
}

export type McpTokenActionState = { token?: string; error?: string };

export async function createWorkspaceMcpToken(_previous: McpTokenActionState, formData: FormData): Promise<McpTokenActionState> {
  if (!configured()) return { error: 'Connect Supabase before creating a workspace token.' };
  const workspaceId = String(formData.get('workspace_id') || '');
  const label = String(formData.get('label') || '').trim();
  const accessLevel = String(formData.get('access_level') || 'read-write');
  if (!/^[0-9a-f-]{36}$/i.test(workspaceId) || !label || label.length > 120) {
    return { error: 'Enter a token label up to 120 characters.' };
  }
  if (!['read-only', 'read-write'].includes(accessLevel)) return { error: 'Choose read-only or production access.' };
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY) return { error: 'Secure token management is not configured for this deployment.' };

  const userClient = await createClient();
  const { data: claimsData } = await userClient.auth.getClaims();
  const userId = claimsData?.claims?.sub;
  if (!userId) return { error: 'Sign in again to create a workspace token.' };
  const { data: membership } = await userClient.from('workspace_members').select('role')
    .eq('workspace_id', workspaceId).eq('user_id', userId).maybeSingle();
  if (!membership || !['owner', 'admin'].includes(membership.role)) {
    return { error: 'Only workspace owners and admins can create MCP access tokens.' };
  }

  const token = `om_live_${randomBytes(32).toString('base64url')}`;
  const tokenHash = createHash('sha256').update(token, 'utf8').digest('hex');
  const admin = createServiceClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false, detectSessionInUrl: false },
  });
  const { error } = await admin.rpc('create_workspace_mcp_token', {
    target_workspace_id: workspaceId,
    target_label: label,
    presented_hash: `\\x${tokenHash}`,
    token_scopes: accessLevel === 'read-only' ? ['mcp:read'] : ['mcp:read', 'mcp:write'],
    target_expires_at: new Date(Date.now() + 90 * 24 * 60 * 60 * 1000).toISOString(),
    actor_id: userId,
  });
  if (error) return { error: 'Could not create the token. Check the Studio migration and try again.' };
  return { token };
}

export async function revokeWorkspaceMcpToken(formData: FormData) {
  if (!configured()) redirect('/?notice=configure-supabase');
  const workspaceId = String(formData.get('workspace_id') || '');
  const tokenId = String(formData.get('token_id') || '');
  if (!/^[0-9a-f-]{36}$/i.test(workspaceId) || !/^[0-9a-f-]{36}$/i.test(tokenId)) redirect('/?notice=invalid-workspace');
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY) redirect('/?notice=credential-storage-unavailable#mcp-access');
  const userClient = await createClient();
  const { data: claimsData } = await userClient.auth.getClaims();
  const userId = claimsData?.claims?.sub;
  if (!userId) redirect('/?notice=sign-in');
  const { data: membership } = await userClient.from('workspace_members').select('role')
    .eq('workspace_id', workspaceId).eq('user_id', userId).maybeSingle();
  if (!membership || !['owner', 'admin'].includes(membership.role)) redirect('/?notice=provider-admin-required#mcp-access');

  const admin = createServiceClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false, detectSessionInUrl: false },
  });
  const { data: revoked, error } = await admin.rpc('revoke_workspace_mcp_token', {
    target_workspace_id: workspaceId,
    target_token_id: tokenId,
    actor_id: userId,
  });
  if (error) redirect('/?notice=mcp-token-revoke-failed#mcp-access');
  if (!revoked) redirect('/?notice=mcp-token-already-revoked#mcp-access');
  revalidatePath('/');
  redirect('/?notice=mcp-token-revoked#mcp-access');
}
