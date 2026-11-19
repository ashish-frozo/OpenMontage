-- One reusable creator brand brief per workspace. Project briefs take a
-- snapshot so later brand edits do not silently rewrite work in progress.
create table public.workspace_brand_profiles (
  workspace_id uuid primary key references public.workspaces(id) on delete cascade,
  brand_name text not null check (length(trim(brand_name)) between 1 and 120),
  audience text not null default '' check (length(audience) <= 500),
  voice text not null default '' check (length(voice) <= 2000),
  visual_direction text not null default '' check (length(visual_direction) <= 2000),
  avoid_terms text[] not null default '{}',
  color_palette text not null default '' check (length(color_palette) <= 240),
  updated_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.workspace_brand_profiles enable row level security;
create policy brand_profile_read on public.workspace_brand_profiles
  for select to authenticated using (public.is_workspace_member(workspace_id));
create policy brand_profile_insert on public.workspace_brand_profiles
  for insert to authenticated with check (
    public.has_workspace_role(workspace_id, array['owner','admin'])
    and updated_by = (select auth.uid())
  );
create policy brand_profile_update on public.workspace_brand_profiles
  for update to authenticated using (public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (
    public.has_workspace_role(workspace_id, array['owner','admin'])
    and updated_by = (select auth.uid())
  );
create trigger brand_profile_workspace_immutable before update on public.workspace_brand_profiles
  for each row execute function public.prevent_workspace_transfer();
grant select, insert, update on public.workspace_brand_profiles to authenticated;
grant all on public.workspace_brand_profiles to service_role;
