-- Durable private media for hosted Studio jobs. Access is mediated by the
-- workspace-authorizing MCP and five-minute signed object URLs.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'studio-media', 'studio-media', false, 21474836480,
  array['video/mp4','video/quicktime','video/webm','video/x-matroska',
        'audio/wav','audio/mpeg','audio/mp4','audio/aac','audio/ogg','audio/flac',
        'image/png','image/jpeg','image/webp','image/gif',
        'text/plain','text/vtt','application/octet-stream']
)
on conflict (id) do update set
  public = false,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

create table if not exists public.studio_media_objects (
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid not null,
  relative_path text not null check (relative_path !~ '(^/|(^|/)\.\.?(/|$))' and relative_path ~ '^(renders|assets)/'),
  object_key text not null unique,
  filename text not null,
  mime_type text not null,
  bytes bigint not null check (bytes > 0 and bytes <= 21474836480),
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  primary key (workspace_id, project_id, relative_path),
  foreign key (workspace_id, project_id) references public.projects(workspace_id, id) on delete cascade
);

alter table public.studio_media_objects enable row level security;
revoke all on public.studio_media_objects from anon, authenticated;
grant select, insert, update, delete on public.studio_media_objects to service_role;

comment on table public.studio_media_objects is
  'Private hosted Studio object index. Only the trusted MCP service role may read or write these records.';
