# Motion and style library

The curated library extends the existing YAML playbooks without changing their
validated schema. `styles/community/catalog.json` is the discovery source for
additional recipes and motion resources.

## MCP discovery

- `factory_styles(plugin="openmontage", query="...", offset=0, limit=30)` lists
  built-in playbooks and community style recipes.
- `factory_style(style_id="community-line-boil")` returns the full recipe,
  renderer compatibility, asset needs and upstream provenance.
- `factory_motion_resources(query="...", offset=0, limit=30)` lists skills and
  external template libraries with their integration status and rights notes.
- `factory_instruction(plugin="openmontage",
  name=".agents/skills/lottiefiles-motion-design/SKILL.md")` reads a bundled
  skill. Declared Markdown references under that skill directory can also be
  retrieved this way.

The calling AI remains the creative router: it compares the selected style and
brief against `factory_operations`, pipeline constraints and live health before
choosing an executable renderer. A style or skill record is creative guidance,
not proof that the referenced runtime is installed.

## Add a style recipe

Add an entry to `styles/community/catalog.json` with a stable unique `id`,
display `name`, short `description`, `category`, `best_for` use cases,
concrete `palette`, `motion.principles`, `composition`, and `asset_requirements`
that an AI can translate into native renderer inputs. Set `renderers` only to
known representations; this is a compatibility hint, not a health result.
Record the exact upstream URL, license, and a precise note describing what was
adapted or copied.

For additional skills or template catalogs, update `motion_resources` with a
stable ID, upstream source and license, local instruction path when bundled,
compatible runtimes, and a `kind` that distinguishes vendored skills/code from
catalog-only references. Keep upstream license/NOTICE files beside copied
content. Do not bundle third-party fonts, sample media, characters, or assets
based only on a repository's top-level license.

## Current integration boundaries

- The 15 `community-*` recipes are OpenMontage-authored descriptions inspired
  by `mg-styles-15`; no upstream files, prompts, fonts, audio samples, or films
  are copied.
- HyperFrames and Remotion template repositories are catalog references. The
  agent must review and adapt examples to frame-driven rendering.
- LottieFiles' MIT skill and Anidoodle's Apache-2.0 skill/engine source are
  vendored with provenance. Anidoodle's Node dependencies are not installed.
- Huashu's MIT skill and reference docs are vendored; its runtime, scripts,
  media, and fonts are not bundled. Its instructions are primarily Chinese.
- ClaudeAnimationBase's MIT animation guide is included, but its renderer,
  sample media, and Clawd character are excluded.
- ManimCE and ManimGL skills are already present under `.agents/skills/`.
  Renderer availability is determined independently by live capabilities.

To make any library executable through the factory, implement and register a
`BaseTool` adapter, expose its native parameter schema, report health and
dependencies, and grant it to the appropriate pipeline. Do not infer
availability from this catalog.

## Executable named motions (small-model authoring)

`factory_motion_presets(query="", offset=0, limit=30)` discovers 42 local,
original GSAP recipes: fades, directional slides, bounce and elastic entrances,
zoom/pop/shrink, flips, spins, directional wipes, pulse, float, wiggle and nudge.
`factory_compile_motion` accepts a bounded plan and returns JavaScript source:

```json
{"params":{"cues":[{"preset":"pop_in","target":".headline","at":0,"duration":0.6}],"reduced_motion":false}}
```

Call the returned `applyMotion(tl)` after DOM creation with the host's GSAP
paused timeline. The compiler does not install GSAP, create a workspace, render
video, choose a runtime, or bypass pipeline gates. Save the source inside the
approved authored workspace and use its normal check/render route. This is a
GSAP-only authoring helper, not a new Remotion cut type. For staggered classes,
supply the matching element count for duration accounting. Avoid simultaneous
cues that animate the same target properties. Reduced motion replaces geometric
motion with opacity changes. Preview the result before final rendering.

For small models: discover filtered ids, compile a few cues, inspect errors,
then use existing stage context, route validation and checkpoint tools. This
reduces code generation but does not establish end-to-end model reliability;
that requires repeated production tasks with the chosen model and budget.

Design references: [GSAP timelines](https://gsap.com/docs/v3/GSAP/Timeline/)
for explicit positioning/stagger and [MCP tool contracts](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/draft/server/tools.mdx)
for typed inputs and discoverable tool results. No upstream animation assets
or template source were copied.

## Executable data-driven scene adapters

The next integration layer is implemented in `lib/motion_scene.py` and
`motion-runtime/`. Discover its versioned contract and per-recipe examples with
`factory_motion_scene_schema`; use `factory_validate_motion_scene` to obtain
field-level errors. Submit `openmontage:motion_scene` through an approved assets
route for preview PNGs or MP4 clips. It supports Rough.js, Flubber, ELK, Lottie,
curated GL transitions, Matter.js, tsParticles initialization, Vega and MapLibre.
Rhubarb cue playback is a tenth recipe; `rhubarb_lipsync` produces the cues when
a compatible executable is installed. `timeline_export` writes native OTIO.

See [runtime setup and limits](../../motion-runtime/README.md). These are bounded
recipes, not complete wrappers for every upstream feature. Runtime availability
is separate from schema availability. Rhubarb v1.14.0 macOS is x86_64 and failed
to execute on the development Apple Silicon machine; it is reported unavailable.
Browser recipes and OTIO do not depend on Rhubarb being installed.
