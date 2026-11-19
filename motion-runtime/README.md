# Local motion recipe runtime

Install: `npm ci && node build.mjs && npx playwright install chromium`.
Python OTIO extension: `pip install -r ../requirements-motion.txt`.
Alternatively explicitly set `MOTION_BROWSER_CHANNEL=chrome` to use installed
Chrome. Node >=22 and FFmpeg are required. Dependencies are exact-pinned by
package-lock.json. Never load runtime libraries from a CDN during capture.

Use `factory_motion_scene_schema` / `factory_validate_motion_scene`, then submit
`openmontage:motion_scene` through an assets-stage route. This produces clips
for the existing compositor; it does not switch the approved final runtime.
Schema v1: at most 30 objects, 60 seconds, 1920px per axis and a total pixel
budget. Each object has its own recipe, box and time interval. Duplicate ids
and invalid timing/bounds fail before rendering. Browser capture rejects label
overflow and checks exact backward-seek pixel reproducibility. Art review is
still required. Cross-browser/OS pixel identity is not promised.

Preview output is a directory of three PNGs plus report.json. Render output is
an MP4; inspect its returned verification report. Scenes do not accept scripts or remote URLs. The media recipe accepts approved
local PNG/JPEG/WebP paths, rasterized and embedded by Python before capture. Lottie is embedded vector-only JSON. GL
transitions currently operate between color surfaces, maps show an offline
route with no basemap, and mouth playback supports either the original face or reusable cue-keyed face sprites. Use media_transition for real footage/image transitions. These
are bounded initial integrations, not complete exposure of each library API.
Particles use tsParticles to instantiate the set, then our seeded analytic
trajectories for deterministic seeking; they are not arbitrary tsParticles
presets. Matter simulation is baked at the scene frame rate.

Rhubarb: install upstream v1.14.0 for your platform, retain its LICENSE.md and
third-party notices, and set RHUBARB_BINARY or put it on PATH. `rhubarb_lipsync`
returns mouthCues, copied to the mouth recipe's mouth_cues input. Its health is
independent of the browser renderer. OTIO export supports ordered clips and
source ranges, not effect round-tripping.

Licenses: Rough.js, Flubber, Lottie-web, Matter.js, tsParticles: MIT; ELK.js:
EPL-2.0; Vega: BSD-3-Clause; MapLibre: BSD core plus included notices; GL
Transitions: per-shader MIT/BSD headers. Dependencies retain their upstream
license files in node_modules; ship corresponding notices with redistributed
bundles. Runtime code and sample fixtures here are original. Lottie artwork,
fonts, audio and any future map tiles require separate provenance.

Tests: `MOTION_BROWSER_CHANNEL=chrome .venv/bin/python -m pytest
 tests/content_factory/test_motion_scene.py` from repository root. These test
actual rendering, not model success. No inexpensive-model benchmark has yet
been run; do not claim a success percentage based on these fixtures.

Preview publication: each run writes to a unique `run-*` child directory. Read
`latest.json` for the current attempt's status and output path; failed attempts
publish `status: failed` with no current output. Older run directories are history,
not the latest result. Health checks now launch the selected browser with a timeout.
