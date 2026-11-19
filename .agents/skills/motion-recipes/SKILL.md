---
name: motion-recipes
description: Data-driven local motion scene production and validation.
---
Use factory_motion_scene_schema, then factory_validate_motion_scene. Choose a
recipe and supply bounded data; do not write renderer code. This is templated
asset generation, not atelier. Submit openmontage:motion_scene through normal
assets-stage routes after required approvals; final composition stays with the
approved runtime. Preview mode writes first/middle/last PNGs and a verification
report to output_path (directory). Render mode writes an MP4. Review previews
before using clips. No network or user scripts are supported in scenes.

Recipes: sketch (Rough.js), morph (Flubber SVG paths), diagram (ELK nodes/edges),
lottie (embedded vector-only animation), transition (three curated GL effects,
currently color surfaces), physics (Matter falling boxes), particles (tsParticles
initialization plus bounded analytic trajectories), chart (Vega bars), map
(MapLibre offline route on plain background; no downloaded basemap), mouth
(simple original cartoon face consuming Rhubarb cues).

Use rhubarb_lipsync for audio -> JSON mouthCues; copy those into mouth_cues.
The native Rhubarb executable is optional and health must be checked. It does
not create the character artwork or provide photorealistic face animation.
Use timeline_export for ordered clip path/start/duration -> OTIO, not effects
round-tripping. Report effects_preserved=false.

Every object owns its recipe and has a unique id, explicit box and interval.
Objects can intentionally overlap visually; conflicting duplicate ids are
rejected. Motion holds its final state after its interval. Reduced motion freezes
recipe progress at its endpoint. Fix bounds, timing, missing data and text
fit errors before retrying. Rendering tests backward seek determinism.

Media extensions: `media` accepts an approved local image_path (PNG/JPEG/WebP),
zoom_end and pan_x/pan_y. Python embeds bounded raster data before capture; remote
URLs and scripts remain unsupported. `mouth_images` maps X and each used cue to
local face sprites, preserving the same character design across shots. Narration
is mixed separately with sound_design using the same cue times. Use
media_transition for transitions between actual footage/images. Preview runs
publish latest.json pointing to a unique run directory; do not reuse an old run
when the current manifest says failed.
