import {
  ArrowDownRight, ArrowUpRight, Check, Clapperboard, FolderOpen,
  Layers3, LogOut, Play, PlugZap, Sparkles,
} from 'lucide-react';
import { createWorkspace, saveBrief, startClipFromUrl, saveBrandProfile, saveProviderCredential, sendSignInLink, signOut } from './actions';
import { createClient } from '@/lib/supabase/server';
import { createClient as createServiceClient } from '@supabase/supabase-js';
import RevokeCredential from './components/revoke-credential';
import JobActivity from './components/job-activity';
import McpAccess from './components/mcp-access';
import ConnectEngine from './components/connect-engine';
import StartResearch from './components/start-research';
import ClipResults from './components/clip-results';
import ResearchResults from './components/research-results';
import RenderExport from './components/render-export';
import StylePicker from './components/style-picker';

type Workspace = { id: string; name: string; slug: string };
type Membership = { role: string; workspaces: Workspace | null };
type Project = { id: string; title: string; platform: string; format: string; status: string; brief: Record<string, unknown> | null; created_at: string; current_stage: string | null; current_checkpoint_status: string | null; approval_needed: boolean; stage_updated_at: string | null };
type Job = { id: string; project_id: string; operation: string; status: string; progress: number; progress_label: string; created_at: string; updated_at: string };
type EngineConnection = { id: string; label: string; status: string; last_seen_at: string | null };
type EngineCapability = { id: string; operation_key: string; display_name: string; description: string; pipeline_stage: string; runtime: string; estimated_cost_usd: number | null };
type ProviderConnection = { id: string; provider: string; label: string; credential_hint: string | null; status: string };
type BrandProfile = { brand_name: string; audience: string; voice: string; visual_direction: string; avoid_terms: string[]; color_palette: string };
type McpToken = { id: string; label: string; scopes: string[]; created_at: string; expires_at: string; revoked_at: string | null; last_used_at: string | null };

function publicMcpEndpoint(value: string | undefined) {
  if (!value) return '';
  try {
    const url = new URL(value);
    const secure = url.protocol === 'https:' || (url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname));
    if (!secure || url.username || url.password || url.search || url.hash) return '';
    return `${url.origin}${url.pathname}`;
  } catch {
    return '';
  }
}

const noticeText: Record<string, string> = {
  'configure-supabase': 'Connect a Supabase project to enable sign-in and workspace data.',
  'invalid-email': 'Enter a valid email address and try again.',
  'sign-in-failed': 'We could not send the sign-in link. Check the email address and try again.',
  'sign-in-rate-limited': 'A sign-in email was just requested. Wait about a minute, then use the newest link in your inbox or spam folder.',
  'check-email': 'Your secure sign-in link is on its way. Check your inbox.',
  'sign-in-expired': 'That sign-in link is invalid or expired. Request a fresh one.',
  'sign-in': 'Sign in to continue.',
  'invalid-workspace': 'Workspace names must contain at least one letter or number and stay under 120 characters.',
  'workspace-name-taken': 'That workspace address is already in use. Add a distinctive word to the workspace name.',
  'workspace-failed': 'We could not create the workspace. Please try again.',
  'workspace-load-failed': 'We could not load your workspace. Refresh the page or sign out and back in.',
  'workspace-created': 'Workspace created. Your creator desk is ready.',
  'invalid-brief': 'Check the idea, audience, region, goal, research time frame, video length, and starting format.',
  'invalid-platform': 'Choose YouTube, Instagram, or both.',
  'invalid-format': 'Choose a supported video format.',
  'workspace-access': 'You no longer have access to that workspace. Refresh and choose a workspace you belong to.',
  'brief-failed': 'We could not save this brief. Please try again.',
  'project-load-failed': 'Your workspace opened, but recent projects could not load. Refresh to try again.',
  'brief-saved': 'Research brief saved. Use it with your connected OpenMontage MCP to gather cited sources and shape the story.',
  'clip-rights': 'Confirm that you own the source video or have permission to process it.',
  'clip-invalid-url': 'Use a secure YouTube link or a direct HTTPS link to a video file.',
  'clip-invalid-options': 'Choose 1–15 clips, a supported hook style, and a cost reserve from $0.01 to $100.',
  'clip-tool-unavailable': 'The connected MCP does not report OpenShorts as available. Check its setup and health before trying again.',
  'clip-preflight-failed': 'The MCP could not validate and save this clip route. No clip job was submitted.',
  'clip-budget-exceeded': 'The preflight estimate exceeds the reserve you entered. No clip job was submitted.',
  'clip-save-failed': 'The route was saved, but Studio could not save the project. No clip job was submitted.',
  'clip-submission-unknown': 'The MCP response was interrupted after submission may have started. Check project activity before retrying.',
  'clip-start-failed': 'Studio could not start this clip workflow. Check the engine connection and project activity before retrying.',
  'clips-started': 'Clip workflow started. Follow its progress and results in project activity.',
  'invalid-brand-profile': 'Check the brand name and keep each brand field within its stated limit.',
  'brand-admin-required': 'Only workspace owners and admins can edit the brand profile.',
  'brand-save-failed': 'We could not save this brand profile. Please try again.',
  'brand-saved': 'Brand profile saved. New briefs will include this guidance.',
  'engine-admin-required': 'Only workspace owners and admins can disconnect an engine.',
  'engine-storage-unavailable': 'Secure engine credentials are not configured on this Studio server.',
  'engine-not-found': 'That engine connection is no longer available. Refresh the page and try again.',
  'engine-revoke-failed': 'Studio could not revoke this engine connection. Try again.',
  'engine-already-revoked': 'That engine connection has already been disconnected.',
  'engine-revoked': 'Engine disconnected. Its workspace token was revoked and its encrypted secret erased.',
  'invalid-provider-credential': 'Check the provider name, label, and API key, then try again.',
  'credential-storage-unavailable': 'Secure credential storage is not configured for this deployment.',
  'provider-admin-required': 'Only workspace owners and admins can connect provider credentials.',
  'provider-save-failed': 'We could not securely save that provider credential. Try again.',
  'provider-label-taken': 'A connection with that provider and label already exists in this workspace.',
  'provider-revoke-failed': 'We could not revoke that provider key. Try again.',
  'provider-already-revoked': 'That provider key is already revoked.',
  'provider-revoked': 'The encrypted provider key was removed and the connection revoked.',
  'provider-saved': 'Provider credential encrypted and saved. The engine must still support this provider before it can use the key.',
  'mcp-token-revoke-failed': 'We could not revoke that MCP token. Try again.',
  'mcp-token-already-revoked': 'That MCP token is already revoked.',
  'mcp-token-revoked': 'MCP token revoked. Connected clients can no longer access this workspace.',
};

function Brand() {
  return <a className="brand" href="/" aria-label="OpenMontage Studio home"><span className="brand-mark" aria-hidden="true"><i /><i /><i /></span><span>openmontage<small>STUDIO</small></span></a>;
}

function SideRail({ workspace, email }: { workspace?: Workspace; email?: string }) {
  return <aside className="rail" aria-label="Workspace navigation">
    <Brand />
    {workspace ? <div className="workspace-switch"><span className="workspace-initial">{workspace.name.slice(0, 1).toUpperCase()}</span><span className="workspace-label">{workspace.name}<small>Creator workspace</small></span><span className="down-caret" aria-hidden="true">⌄</span></div> : null}
    <nav aria-label="Primary">
      <a className="nav-link is-active" href="#create" aria-current="page"><Sparkles aria-hidden="true" />Make a video</a>
      <a className="nav-link" href="#repurpose"><Play aria-hidden="true" />Turn a video into clips</a>
      <a className="nav-link" href="#projects"><FolderOpen aria-hidden="true" />My projects</a>
      {workspace ? <a className="nav-link" href="#workspace-setup"><PlugZap aria-hidden="true" />Setup &amp; tools</a> : null}
    </nav>
    <div className="rail-bottom">
      {email ? <form action={signOut} className="account-row"><span className="account-initial">{email.slice(0, 1).toUpperCase()}</span><span>{email}<small>Signed in</small></span><button aria-label="Sign out" title="Sign out"><LogOut aria-hidden="true" /></button></form> : null}
    </div>
  </aside>;
}

function Notice({ notice }: { notice?: string }) {
  if (!notice) return null;
  const text = noticeText[notice];
  if (!text) return null;
  const isSuccess = ['check-email', 'workspace-created', 'brief-saved', 'brand-saved', 'engine-revoked'].includes(notice);
  return <p className={`notice ${isSuccess ? 'notice-success' : 'notice-error'}`} role="status">{isSuccess ? <Check aria-hidden="true" /> : <ArrowDownRight aria-hidden="true" />}{text}</p>;
}

function SetUpSupabase() {
  return <main className="setup-screen"><div className="setup-wrap"><Brand /><div className="setup-content"><span className="eyebrow">HOSTED STUDIO</span><h1>Your creator workspace,<br /><em>ready to take shape.</em></h1><p>Connect a Supabase project to turn on secure sign-in, workspace creation, and saved video briefs.</p><div className="setup-box"><b>Setup needed</b><p>Add <code>NEXT_PUBLIC_SUPABASE_URL</code> and <code>NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY</code> to <code>apps/studio/.env.local</code>, then apply the Studio migration to that Supabase project.</p><a href="https://github.com/calesthio/OpenMontage/blob/main/docs/saas/architecture.md">Read the hosted architecture <ArrowUpRight aria-hidden="true" /></a></div></div></div></main>;
}

function SignIn({ notice }: { notice?: string }) {
  return <div className="auth-layout"><SideRail /><main className="auth-main"><div className="topline"><span>OpenMontage Studio</span><span className="service-status"><i /> WORKSPACE SERVICE</span></div><section className="auth-intro"><span className="eyebrow">A BETTER WAY TO MAKE THE NEXT ONE</span><h1>Make room for the<br /><em>good ideas.</em></h1><p>Research a story, shape the direction, and turn your idea into a video you can review and own.</p><Notice notice={notice} /><form className="auth-form" action={sendSignInLink} aria-labelledby="signin-title"><h2 id="signin-title">Start with your email</h2><label htmlFor="email">Email address</label><input id="email" name="email" type="email" autoComplete="email" required maxLength={254} placeholder="you@example.com" /><button type="submit">Email me a sign-in link <ArrowUpRight aria-hidden="true" /></button><small>No password to remember. Your workspace stays private.</small></form></section><div className="auth-foot">OPENMONTAGE <span>/</span> RESEARCH FIRST. REVIEW TOGETHER. EXPORT WITH CONTROL.</div></main></div>;
}

function CreateWorkspace({ notice, email }: { notice?: string; email: string }) {
  return <div className="auth-layout"><SideRail email={email} /><main className="auth-main"><div className="topline"><span>Set up your Studio</span><form action={signOut}><button className="quiet-button" type="submit">Sign out</button></form></div><section className="auth-intro narrow-intro"><span className="eyebrow">YOUR WORKSPACE, YOUR WORK</span><h1>Give your ideas<br /><em>a home.</em></h1><p>Create a private creator workspace. You can add more members later.</p><Notice notice={notice} /><form className="auth-form" action={createWorkspace} aria-labelledby="workspace-heading"><h2 id="workspace-heading">Name your workspace</h2><label htmlFor="workspace-name">Workspace name</label><input id="workspace-name" name="name" autoComplete="organization" required minLength={1} maxLength={120} placeholder="Your name or channel" /><button type="submit">Create workspace <ArrowUpRight aria-hidden="true" /></button><small>Workspace URLs are created from this name. You can change the display name later.</small></form></section><div className="auth-foot">OPENMONTAGE <span>/</span> PRIVATE BY DEFAULT.</div></main></div>;
}

function ProjectList({ workspaceId, projects, unavailable = false }: { workspaceId: string; projects: Project[]; unavailable?: boolean }) {
  if (unavailable) return <div className="project-empty"><span className="empty-shape"><Layers3 aria-hidden="true" /></span><b>Projects could not load</b><p>Refresh the workspace before making changes to a project.</p></div>;
  if (projects.length === 0) return <div className="project-empty"><span className="empty-shape"><Layers3 aria-hidden="true" /></span><p>Saved briefs and finished videos will appear here.</p></div>;
  const projectStatus = (status: string) => ({
    brief: 'Ready for research', research: 'Research in progress', in_progress: 'In production',
    review: 'Needs your review', complete: 'Ready to export', archived: 'Archived',
  }[status] || status.replaceAll('_', ' '));
  return <ul className="project-list">{projects.map(project => {
    const savedClips = Array.isArray(project.brief?.clip_outputs) ? project.brief.clip_outputs.filter((item): item is { title: string; url: string } => {
      const row = item && typeof item === 'object' ? item as Record<string, unknown> : null;
      return Boolean(row && typeof row.title === 'string' && typeof row.url === 'string');
    }) : [];
    return <li id={`project-${project.id}`} key={project.id}><span className="project-glyph"><Clapperboard aria-hidden="true" /></span><span className="project-copy"><strong>{project.title}</strong><small>{project.platform} <i /> {project.format} <i /> {project.current_stage ? `${project.current_stage.replaceAll('_', ' ')} · ${project.current_checkpoint_status?.replaceAll('_', ' ') || 'started'}` : projectStatus(project.status)}</small></span><span className={`project-state ${project.approval_needed || project.status === 'review' ? 'project-state-review' : ''}`}>{project.approval_needed ? 'APPROVAL NEEDED' : projectStatus(project.status).toUpperCase()}</span><StartResearch workspaceId={workspaceId} projectId={project.id} status={project.status} /><ResearchResults workspaceId={workspaceId} projectId={project.id} status={project.status} currentStage={project.current_stage} /><RenderExport workspaceId={workspaceId} projectId={project.id} />{project.brief?.pipeline === 'openshorts-clipping' ? <ClipResults workspaceId={workspaceId} projectId={project.id} initialStatus={String(project.brief.clip_status || '')} initialClips={savedClips} /> : null}</li>;
  })}</ul>;
}

function NextActionFocus({ projects, jobs, projectsError, jobsError, engineLive }: { projects: Project[]; jobs: Job[]; projectsError: boolean; jobsError: boolean; engineLive: boolean }) {
  const reviewProjects = projects.filter(project => project.status === 'review' || project.approval_needed);
  const waitingJobs = jobs.filter(job => job.status === 'waiting_approval');
  const projectById = new Map(projects.map(project => [project.id, project]));
  const activeJob = jobs.find(job => ['running', 'queued', 'cancelling', 'reconciling', 'interrupted'].includes(job.status));
  const failedJob = jobs.find(job => job.status === 'failed');
  const activeProject = activeJob ? projectById.get(activeJob.project_id) : undefined;
  const briefProject = projects.find(project => project.status === 'brief');
  const researchProject = projects.find(project => project.status === 'research');
  const productionProject = projects.find(project => project.status === 'in_progress');
  const exportProject = projects.find(project => project.status === 'complete');
  let focus: { title: string; detail: string; href: string; action: string; tone?: string; kicker?: string };

  if (projectsError || jobsError) {
    focus = { title: 'Workspace status could not load', detail: 'Refresh before relying on project, job, or approval status.', href: '#projects', action: 'Open projects', tone: 'attention' };
  } else if (reviewProjects.length || waitingJobs.length) {
    const project = reviewProjects[0] || projectById.get(waitingJobs[0].project_id);
    focus = { title: project ? `Review ${project.title}` : 'A project needs your approval', detail: 'An approval gate is waiting. Review the saved work before production continues.', href: project ? `#project-${project.id}` : '#workspace-setup', action: 'Review project', tone: 'attention', kicker: 'APPROVAL NEEDED' };
  } else if (activeJob) {
    const title = activeProject?.title || 'A video project';
    const uncertain = ['reconciling', 'interrupted'].includes(activeJob.status);
    focus = { title: uncertain ? `Check ${title}` : `${title} is ${activeJob.status === 'queued' ? 'in the queue' : activeJob.status === 'cancelling' ? 'stopping' : 'in production'}`, detail: uncertain ? 'The last job has an uncertain outcome. Review it before starting another attempt.' : activeJob.progress_label || 'Production activity will update as the job moves forward.', href: activeProject ? `#project-${activeProject.id}` : '#workspace-setup', action: uncertain ? 'Check project' : 'View progress', tone: uncertain ? 'attention' : undefined };
  } else if (failedJob) {
    const title = projectById.get(failedJob.project_id)?.title || 'a video project';
    focus = { title: `Review the failed step for ${title}`, detail: 'Inspect its result and provider status before retrying; work may have had external effects.', href: '#workspace-setup', action: 'Review job', tone: 'attention' };
  } else if (briefProject) {
    focus = { title: engineLive ? `Start research on ${briefProject.title}` : 'Connect an engine to start research', detail: engineLive ? 'Your brief is saved. Research is the next step, and no paid generation starts here.' : 'Your brief is saved. Connect an OpenMontage MCP engine before gathering sources.', href: engineLive ? `#project-${briefProject.id}` : '#workspace-setup', action: engineLive ? 'Open brief' : 'Open setup' };
  } else if (researchProject) {
    focus = { title: `Review research for ${researchProject.title}`, detail: 'Check source leads and evidence before shaping the script.', href: `#project-${researchProject.id}`, action: 'Review research' };
  } else if (productionProject) {
    focus = { title: `Continue ${productionProject.title}`, detail: 'Open the project to see the current production stage and its next approval gate.', href: `#project-${productionProject.id}`, action: 'Open project' };
  } else if (exportProject) {
    focus = { title: `${exportProject.title} is ready to export`, detail: 'Preview the finished video and prepare a platform handoff.', href: `#project-${exportProject.id}`, action: 'Preview video' };
  } else {
    focus = { title: 'Write your first research brief', detail: 'Start with an idea, audience, and goal. Studio will show what happens next.', href: '#create', action: 'Create a brief' };
  }

  return <section className={`approval-focus next-action-focus ${focus.tone === 'attention' ? 'approval-focus-needed' : ''}`} aria-label={focus.kicker === 'APPROVAL NEEDED' ? 'Approval needed' : 'Your next step'}>
    <span className="approval-indicator" aria-hidden="true">{focus.tone === 'attention' ? '!' : <Play />}</span>
    <div><span className="eyebrow">{focus.kicker || 'YOUR NEXT STEP'}</span><strong>{focus.title}</strong><p>{focus.detail}</p></div>
    <a href={focus.href}>{focus.action} <ArrowUpRight aria-hidden="true" /></a>
  </section>;
}

function ProviderPanel({ workspace, role, providers }: { workspace: Workspace; role: string; providers: ProviderConnection[] }) {
  const canManage = ['owner', 'admin'].includes(role);
  return <section id="providers" className="provider-panel">
    <div className="recent-head"><div><span className="eyebrow">PRIVATE TO THIS WORKSPACE</span><h2>AI providers</h2></div><span className="project-total">{providers.length} saved</span></div>
    {providers.length ? <ul className="provider-list">{providers.map(provider => <li key={provider.id}><span className="provider-mark" aria-hidden="true">{provider.provider.slice(0, 1).toUpperCase()}</span><span><strong>{provider.label}</strong><small>{provider.provider} · {provider.credential_hint || 'credential stored'}</small></span><span className="provider-status">{provider.status === 'connected' ? 'SAVED' : provider.status.replaceAll('_', ' ').toUpperCase()}</span>{canManage && provider.status !== 'revoked' ? <RevokeCredential workspaceId={workspace.id} connectionId={provider.id} /> : null}</li>)}</ul> : <p className="provider-empty">Save a model provider key for an OpenMontage engine. Provider charges remain on that account; key testing and engine delivery are not available yet.</p>}
    {canManage ? <details className="provider-connect"><summary>Add a provider credential</summary><form action={saveProviderCredential} className="provider-form"><input type="hidden" name="workspace_id" value={workspace.id} /><div className="field"><label htmlFor="provider-name">Provider ID</label><input id="provider-name" name="provider" required maxLength={64} placeholder="e.g. openrouter, fal.ai, openai" autoComplete="off" /></div><div className="field"><label htmlFor="provider-label">Connection label</label><input id="provider-label" name="label" required maxLength={120} placeholder="Personal OpenRouter key" autoComplete="off" /></div><div className="field"><label htmlFor="provider-key">API key or credential map</label><input id="provider-key" name="api_key" type="password" required minLength={8} maxLength={4096} autoComplete="new-password" placeholder="Paste an API key or a JSON credential map" /></div><p className="credential-notice">The credential is encrypted before storage and never shown again. Use provider ID google for Google service-account JSON. For tools needing multiple environment values, paste a JSON map such as &#123;&quot;HIGGSFIELD_API_KEY&quot;:&quot;…&quot;,&quot;HIGGSFIELD_API_SECRET&quot;:&quot;…&quot;&#125;. Only workspace owners and admins can add credentials.</p><button type="submit">Encrypt and save key <ArrowUpRight aria-hidden="true" /></button></form></details> : <p className="provider-empty">Ask a workspace owner or admin to connect a provider key.</p>}
  </section>;
}

function BrandProfilePanel({ workspace, role, profile }: { workspace: Workspace; role: string; profile: BrandProfile | null }) {
  const canManage = ['owner', 'admin'].includes(role);
  return <section id="brand" className="brand-panel">
    <div className="recent-head"><div><span className="eyebrow">GUIDANCE FOR EVERY NEW BRIEF</span><h2>Brand profile</h2></div><span className="project-total">{profile ? 'ACTIVE' : 'OPTIONAL'}</span></div>
    <p className="brand-intro">Set the audience, voice, and visual direction your videos should carry. Each new brief saves a snapshot so later edits don’t rewrite an in-progress project.</p>
    {canManage ? <form action={saveBrandProfile} className="brand-form"><input type="hidden" name="workspace_id" value={workspace.id} />
      <div className="field"><label htmlFor="brand-name">Channel or brand name</label><input id="brand-name" name="brand_name" autoComplete="organization" required minLength={1} maxLength={120} defaultValue={profile?.brand_name || ''} placeholder="e.g. Clear Ideas with Maya" /></div>
      <div className="field"><label htmlFor="brand-audience">Who your channel serves</label><textarea id="brand-audience" name="brand_audience" autoComplete="off" rows={2} maxLength={500} defaultValue={profile?.audience || ''} placeholder="Audience, knowledge level, and what they care about" /></div>
      <div className="field"><label htmlFor="brand-voice">Voice and tone</label><textarea id="brand-voice" name="brand_voice" autoComplete="off" rows={2} maxLength={2000} defaultValue={profile?.voice || ''} placeholder="How the narration should sound, with a few traits or examples" /></div>
      <div className="field"><label htmlFor="visual-direction">Visual direction</label><textarea id="visual-direction" name="visual_direction" autoComplete="off" rows={2} maxLength={2000} defaultValue={profile?.visual_direction || ''} placeholder="Color, typography, image treatment, and motion preferences" /></div>
      <div className="field"><label htmlFor="avoid-terms">Terms or claims to avoid <span className="optional">ONE PER LINE</span></label><textarea id="avoid-terms" name="avoid_terms" autoComplete="off" rows={2} maxLength={3240} defaultValue={(profile?.avoid_terms || []).join('\n')} placeholder="Banned phrases, sensitive claims, or wording to avoid" /></div>
      <div className="field"><label htmlFor="brand-colors">Color palette <span className="optional">OPTIONAL</span></label><input id="brand-colors" name="color_palette" autoComplete="off" maxLength={240} defaultValue={profile?.color_palette || ''} placeholder="e.g. #14213D, #FCA311, warm white" /></div>
      <button type="submit">Save brand profile <ArrowUpRight aria-hidden="true" /></button>
    </form> : <p className="provider-empty">Ask a workspace owner or admin to update the brand profile.</p>}
  </section>;
}

function CreatorDesk({ workspace, email, role, projects, projectsError, jobs, jobsError, capabilities, engineLive, providers, brandProfile, engineConnections, mcpTokens, mcpEndpoint, engineStorageReady, notice }: { workspace: Workspace; email: string; role: string; projects: Project[]; projectsError: boolean; jobs: Job[]; jobsError: boolean; capabilities: EngineCapability[]; engineLive: boolean; providers: ProviderConnection[]; brandProfile: BrandProfile | null; engineConnections: EngineConnection[]; mcpTokens: McpToken[]; mcpEndpoint: string; engineStorageReady: boolean; notice?: string }) {
  const hasHistory = projects.length > 0 || jobs.length > 0 || projectsError || jobsError;
  const engineStatus = engineLive
    ? `Engine ready · ${capabilities.length} tools`
    : !mcpEndpoint || !engineStorageReady
      ? 'Engine setup needed'
      : 'Engine not connected';
  const missingEngineConfig = [
    !mcpEndpoint ? 'NEXT_PUBLIC_MCP_ENDPOINT' : null,
    !process.env.SUPABASE_SERVICE_ROLE_KEY ? 'SUPABASE_SERVICE_ROLE_KEY' : null,
    !process.env.STUDIO_CREDENTIAL_ENCRYPTION_KEY ? 'STUDIO_CREDENTIAL_ENCRYPTION_KEY' : null,
  ].filter((key): key is string => Boolean(key));
  const clipToolAvailable = capabilities.some(capability => capability.operation_key.endsWith('openshorts_process_video'));
  return <div className="studio-layout"><SideRail workspace={workspace} email={email} /><main className="desk creator-desk">
    <header className="topline"><div><span>{workspace.name}</span><span className="crumb-divider">/</span><b>Studio</b></div><a className={`engine-status-link ${engineLive ? 'is-ready' : ''}`} href="#workspace-setup"><i />{engineStatus}<ArrowDownRight aria-hidden="true" /></a></header>
    <Notice notice={notice} />
    {hasHistory ? <NextActionFocus projects={projects} jobs={jobs} projectsError={projectsError} jobsError={jobsError} engineLive={engineLive} /> : null}
    <div className="creator-column">
      <section id="create" className="video-brief" aria-labelledby="brief-title">
        <h1 id="brief-title">What should we make?</h1>
        <p className="brief-intro">Start with an idea. Choose a visual direction; research and story planning come next.</p>
        <form className="brief-form" action={saveBrief} aria-labelledby="brief-title">
          <input type="hidden" name="workspace_id" value={workspace.id} />
          <div className="brief-canvas">
            <div className="idea-panel"><span className="idea-step">01 <i>YOUR IDEA</i></span><div className="field idea-field"><label htmlFor="idea">What story do you want to tell?</label><textarea id="idea" name="title" rows={4} required maxLength={240} placeholder="A question, a person, or an idea you want to explore…" /><small>Start with a rough thought. We’ll help shape it into a researched story.</small></div></div>
            <StylePicker />
          </div>
          <div className="brief-primary-options">
            <div className="field"><label htmlFor="platform">Platform</label><select id="platform" name="platform" defaultValue="youtube"><option value="youtube">YouTube</option><option value="instagram">Instagram</option><option value="multi">YouTube &amp; Instagram</option></select></div>
            <div className="field"><label htmlFor="format">Video shape</label><select id="format" name="format" defaultValue="vertical"><option value="vertical">Vertical · 9:16</option><option value="landscape">Landscape · 16:9</option><option value="square">Square · 1:1</option></select></div>
          </div>
          <details className="brief-options"><summary>Fine-tune your brief <span>Audience, goal &amp; length</span></summary>
            <div className="optional-fields">
              <div className="field"><label htmlFor="audience">Who is it for?</label><input id="audience" name="audience" maxLength={120} placeholder="e.g. first-time founders" /></div>
              <div className="field"><label htmlFor="region">Audience region <span className="optional">OPTIONAL</span></label><input id="region" name="region" maxLength={120} placeholder="e.g. India or global English speakers" /></div>
              <div className="field"><label htmlFor="goal">What should viewers get?</label><select id="goal" name="goal" defaultValue="teach"><option value="teach">Learn something useful</option><option value="entertain">Enjoy a good story</option><option value="inspire">Feel inspired to act</option><option value="persuade">See a new point of view</option></select></div>
              <div className="field"><label htmlFor="research-freshness">Research time frame</label><select id="research-freshness" name="research_freshness" defaultValue="evergreen"><option value="evergreen">Evergreen background · free search</option><option value="current" disabled>Current and recent · not enabled yet</option><option value="last_30_days" disabled>Developments in the last 30 days · not enabled yet</option></select></div>
              <div className="field"><label htmlFor="duration">Target length</label><select id="duration" name="duration" defaultValue="60_90"><option value="30_60">30–60 seconds</option><option value="60_90">60–90 seconds</option><option value="180_300">3–5 minutes</option></select></div>
            </div>
          </details>
          <div className="form-end"><span><Check aria-hidden="true" /> Saves a research brief. No video job or paid generation starts.</span><button type="submit">Save brief <ArrowUpRight aria-hidden="true" /></button></div>
        </form>
      </section>
      <section className="repurpose-card" id="repurpose" aria-labelledby="repurpose-title">
        <div className="repurpose-copy"><span className="idea-step">ANOTHER WAY TO START</span><h2 id="repurpose-title">Turn a long video into short clips</h2><p>Paste a YouTube or direct video link. OpenShorts finds moments, reframes them vertically, and can burn in captions and hooks.</p><span className="repurpose-includes"><i /> Clip selection <i /> Vertical 9:16 <i /> Captions</span></div>
        <form className="repurpose-form" action={startClipFromUrl}>
          <input type="hidden" name="workspace_id" value={workspace.id} />
          <div className="field"><label htmlFor="source-url">Video link</label><input id="source-url" name="source_url" type="url" required placeholder="https://www.youtube.com/watch?v=…" /></div>
          <div className="repurpose-options">
            <div className="field"><label htmlFor="target-clips">Target clips</label><select id="target-clips" name="target_clips" defaultValue="4">{[2, 3, 4, 5, 6, 8, 10].map(count => <option key={count} value={count}>{count} clips</option>)}</select></div>
            <div className="field"><label htmlFor="hook-style">Hook treatment</label><select id="hook-style" name="hook_style" defaultValue="pill"><option value="pill">Rounded pill</option><option value="classic">Classic</option><option value="dark">Dark label</option><option value="yellow">Yellow type</option><option value="outline">Outline</option></select></div>
            <div className="field"><label htmlFor="clip-reserve">Cost reserve · USD</label><input id="clip-reserve" name="estimated_cost_usd" type="number" min="0.01" max="100" step="0.25" defaultValue="1.00" required /><small>Used for MCP cost preflight; actual model usage may differ.</small></div>
          </div>
          <label className="clip-rights"><input type="checkbox" name="captions" defaultChecked /><span>Burn in word-level captions and a hook line.</span></label>
          <label className="clip-rights"><input type="checkbox" name="confirm_rights" required /><span>I own this video or have permission to process it.</span></label>
          {!engineLive ? <p className="clip-availability">Connect the OpenMontage MCP engine in <a href="#workspace-setup">Setup &amp; tools</a> to create clips.</p> : !clipToolAvailable ? <p className="clip-availability">OpenShorts is not reporting available on this engine. Check <a href="#workspace-setup">Setup &amp; tools</a>.</p> : null}
          <button className="clip-submit" type="submit" disabled={!engineLive || !clipToolAvailable}>Create vertical clips <ArrowUpRight aria-hidden="true" /></button>
          <small className="clip-disclosure">Creates an MCP job and may use your configured model credits. No automatic retry if the response is interrupted.</small>
        </form>
      </section>
      <section className="recent projects-section" id="projects" aria-labelledby="projects-title"><div className="recent-head"><div><h2 id="projects-title">Your projects</h2></div><span className="project-total">{projectsError ? 'UNAVAILABLE' : `${projects.length} ${projects.length === 1 ? 'project' : 'projects'}`}</span></div><ProjectList workspaceId={workspace.id} projects={projects} unavailable={projectsError} /></section>
      <details className="workspace-tools" id="workspace-setup"><summary><span>Workspace setup &amp; tools</span><small>Engine connection, provider access &amp; activity</small></summary>
        <div className="workspace-tools-content">
          {!engineLive ? <p className="engine-setup-note"><strong>{engineStatus}.</strong> Add {missingEngineConfig.map((key, index) => <span key={key}>{index ? (index === missingEngineConfig.length - 1 ? ' and ' : ', ') : ''}<code>{key}</code></span>)} to the Studio server environment, then restart it. The endpoint must be a reachable HTTPS MCP server.</p> : null}
          <McpAccess workspaceId={workspace.id} role={role} endpoint={mcpEndpoint} tokens={mcpTokens} />
          <ConnectEngine workspaceId={workspace.id} role={role} endpoint={mcpEndpoint} connections={engineConnections} storageReady={engineStorageReady} />
          <JobActivity workspaceId={workspace.id} projects={projects.map(({ id, title }) => ({ id, title }))} initialJobs={jobs} initialUnavailable={jobsError} />
          <BrandProfilePanel workspace={workspace} role={role} profile={brandProfile} />
          <ProviderPanel workspace={workspace} role={role} providers={providers} />
        </div>
      </details>
    </div>
    <footer className="footer"><span>OPENMONTAGE STUDIO <i>/</i> RESEARCH FIRST. REVIEW TOGETHER. EXPORT WITH CONTROL.</span><span>YOUR WORK IS PRIVATE BY DEFAULT.</span></footer>
  </main></div>;
}

export default async function Home({ searchParams }: { searchParams: Promise<{ notice?: string }> }) {
  const params = await searchParams;
  const mcpEndpoint = publicMcpEndpoint(process.env.NEXT_PUBLIC_MCP_ENDPOINT);
  const engineStorageReady = Boolean(process.env.SUPABASE_SERVICE_ROLE_KEY && process.env.STUDIO_CREDENTIAL_ENCRYPTION_KEY);
  if (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY) return <SetUpSupabase />;

  const supabase = await createClient();
  const { data: claimsData } = await supabase.auth.getClaims();
  const claims = claimsData?.claims;
  if (!claims?.sub) return <SignIn notice={params.notice} />;

  const { data: memberships, error: membershipError } = await supabase
    .from('workspace_members')
    .select('role,workspaces(id,name,slug)')
    .eq('user_id', claims.sub)
    .order('joined_at', { ascending: true });
  const membershipRows = (memberships || []) as unknown as Membership[];
  const activeMembership = membershipRows.find(row => row.workspaces);
  const workspace = activeMembership?.workspaces;
  if (!workspace) {
    if (membershipError) return <CreateWorkspace notice="workspace-load-failed" email={String(claims.email || '')} />;
    return <CreateWorkspace notice={params.notice} email={String(claims.email || '')} />;
  }

  const { data: projects, error: projectsError } = await supabase
    .from('projects')
    .select('id,title,platform,format,status,brief,created_at,current_stage,current_checkpoint_status,approval_needed,stage_updated_at')
    .eq('workspace_id', workspace.id)
    .neq('status', 'archived')
    .order('updated_at', { ascending: false })
    .limit(20);

  const { data: jobs, error: jobsError } = await supabase.from('jobs')
    .select('id,project_id,operation,status,progress,progress_label,created_at,updated_at')
    .eq('workspace_id', workspace.id)
    .order('updated_at', { ascending: false })
    .limit(10);

  const { data: engineRows } = await supabase
    .from('engine_connections')
    .select('id,label,status,last_seen_at')
    .eq('workspace_id', workspace.id);
  const engineConnections = ((engineRows || []) as EngineConnection[]).sort((a, b) =>
    (b.last_seen_at || '').localeCompare(a.last_seen_at || ''),
  );
  const liveEngines = ((engineRows || []) as EngineConnection[]).filter(engine =>
    engine.status === 'connected',
  );
  let capabilities: EngineCapability[] = [];
  if (liveEngines.length) {
    const { data: capabilityRows } = await supabase
      .from('engine_capabilities')
      .select('id,operation_key,display_name,description,pipeline_stage,runtime,estimated_cost_usd')
      .eq('workspace_id', workspace.id)
      .eq('available', true)
      .in('connection_id', liveEngines.map(engine => engine.id))
      .order('pipeline_stage', { ascending: true })
      .order('display_name', { ascending: true });
    capabilities = (capabilityRows || []) as EngineCapability[];
  }

  const { data: providerRows } = await supabase.from('provider_connections')
    .select('id,provider,label,credential_hint,status')
    .eq('workspace_id', workspace.id)
    .order('created_at', { ascending: false });
  const { data: brandProfileRow } = await supabase.from('workspace_brand_profiles')
    .select('brand_name,audience,voice,visual_direction,avoid_terms,color_palette')
    .eq('workspace_id', workspace.id).maybeSingle();

  let mcpTokens: McpToken[] = [];
  if (process.env.SUPABASE_SERVICE_ROLE_KEY) {
    const admin = createServiceClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY, {
      auth: { autoRefreshToken: false, persistSession: false, detectSessionInUrl: false },
    });
    const { data: tokenRows } = await admin.from('workspace_mcp_tokens')
      .select('id,label,scopes,created_at,expires_at,revoked_at,last_used_at')
      .eq('workspace_id', workspace.id)
      .not('label', 'like', 'studio-engine:%')
      .order('created_at', { ascending: false });
    mcpTokens = (tokenRows || []) as McpToken[];
  }

  return <CreatorDesk workspace={workspace} email={String(claims.email || '')} role={activeMembership?.role || 'reviewer'} projects={(projects || []) as Project[]} projectsError={Boolean(projectsError)} jobs={(jobs || []) as Job[]} jobsError={Boolean(jobsError)} capabilities={capabilities} engineLive={liveEngines.length > 0} providers={(providerRows || []) as ProviderConnection[]} brandProfile={(brandProfileRow || null) as BrandProfile | null} engineConnections={engineConnections} mcpTokens={mcpTokens} mcpEndpoint={mcpEndpoint} engineStorageReady={engineStorageReady} notice={projectsError ? 'project-load-failed' : params.notice} />;
}
