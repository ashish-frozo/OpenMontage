# Open-source expansion research

Research date: 2026-11-13. Scope: practical additions for low-cost LLM-controlled video production, especially coded motion. This is a source review and integration design, not an installation or render benchmark. Rankings and implementation effort are engineering judgments. License labels describe upstream code; assets, fonts, weights and dependencies require their own records.

## Recommendation

Prioritize compact data-to-visual adapters over more general-purpose authoring engines. First integrate GL Transitions, Flubber, Rough.js, ELK, Lottie playback and Rhubarb. Together these add transitions, shape transformations, sketch illustration, automatic diagrams, reusable animation assets and talking cartoon characters. Keep the existing render runtimes and approval gates.

The current 42-preset compiler only emits GSAP JavaScript. It does not build or render a complete scene. Its passing unit tests do not demonstrate visual quality or small-model reliability. A validated scene contract plus rendered fixtures is the next necessary infrastructure investment.

## Existing coverage and duplication

Repository guide/catalog and graph inspection show Remotion, HyperFrames, FFmpeg, Blender/Three.js, character animation, Ink Theater, Manim skills, and several community motion skills. Skills and catalog references do not establish runtime installation. Literal dependency checks also found WhisperX inside `tools/analysis/transcriber.py` and librosa in `tools/video/bmts_lite.py`; extend those adapters instead of advertising these as wholly new integrations. Animated Drawings is already referenced by the guide. None of these findings is a live health audit.

## Prioritized candidates

Effort: S = narrow adapter; M = adapter plus render/asset integration; L = another runtime or significant simulation infrastructure. These are relative estimates, not delivery promises. Browser options generally need Node plus the existing browser capture stack; they do not require ML inference GPUs. WebGL options still need a functioning graphics backend.

| Priority / project | New capability and proposed input | Code license / runtime | Integration judgment and principal limitation |
|---|---|---|---|
| P0 [GL Transitions](https://github.com/gl-transitions/gl-transitions) | Named shader transitions between two image/video surfaces: effect, duration, bounded parameters | MIT except two BSD transition headers; WebGL; M | Upstream now describes 100+ transitions and a Remotion adapter. Start with a curated tested subset. Drive progress from frame time; test aspect ratio and alpha. Do not assume every shader works on every backend. |
| P0 [Flubber](https://github.com/veltman/flubber) | SVG shape morphs: source path, destination path, progress | MIT; JS; S | Great fit for compact inputs. Handles mismatched shapes; complex holes/multiple contours need curated fixtures. Repository's last push was 2022-11-08 in API snapshot: pin and own compatibility tests. |
| P0 [Rough.js](https://github.com/rough-stuff/rough) | Sketch diagrams and illustrations: shape, bounds, palette, roughness, seed | MIT; SVG/Canvas; S | Adds deterministic illustration building blocks to existing ink styles. It draws shapes; stroke-reveal timing is our adapter's job. Freeze randomness rather than regenerating geometry every frame. Last push 2024-07-28 in snapshot. |
| P0 [ELK.js](https://github.com/kieler/elkjs) | Automatic node/edge layout: nodes, ports, links, direction | EPL-2.0; JS/worker; M | Removes layout arithmetic from small models. ELK computes positions, not rendering. Lay out once, then animate the resulting SVG in existing runtimes. Inspect EPL notices when distributing modifications. |
| P0 [lottie-web](https://github.com/airbnb/lottie-web) | Playback of curated Lottie files: asset id, segment, playback mapping | MIT; SVG/Canvas; M | Existing Lottie skills need an executable asset player. Use frame seeking, disable autoplay, await asset readiness. Do not ask cheap models to invent complex Lottie JSON. Files and embedded artwork need separate licenses. |
| P0 [Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync) | Narration audio to timed mouth cues mapped to our SVG rig | MIT with third-party notices; native CPU CLI; M | Concrete offline cartoon lip sync, without generative-video inference. Requires designed mouth shapes. Evaluate non-English phonetic mode and actual macOS binary compatibility. Not photorealistic face reenactment. |
| P1 [Vega](https://github.com/vega/vega) | Data-driven charts: chart kind, records, encodings, highlight beats | BSD-3-Clause; JS/SVG/Canvas; M | Complements current chart components with a declarative grammar. Wrap a bounded subset rather than exposing all expressions. Rendering charts and animating narrative beats are separate adapter responsibilities. |
| P1 [Matter.js](https://github.com/liabru/matter-js) | Falling cards, collisions, pendulums, chain reactions: bodies, gravity, constraints | MIT; JS CPU simulation; M | Bake fixed-step simulation to a frame cache. Seeking straight to time t is not equivalent to advancing physics. Avoid arbitrary physics code from the model. |
| P1 [tsParticles](https://github.com/tsparticles/tsparticles) | Confetti, snow, stars, sparks and particle fields: preset, seed, density | MIT; Canvas; M | Large visual range with small inputs. Browser autoplay/randomness must be replaced or controlled. Deterministic offline rendering is an acceptance test, not an assumption. Cap density and lifetime. |
| P1 [PixiJS](https://github.com/pixijs/pixijs) | Sprite choreography, masks, filters, dense 2D scenes | MIT; WebGL/WebGPU; M–L | Useful when DOM/SVG scenes become heavy. Disable autonomous ticker; render explicitly. Build sprite/particle recipes rather than another unrestricted code-generation interface. |
| P1 [MapLibre GL JS](https://github.com/maplibre/maplibre-gl-js) | Geographic stories: locations, route, camera keyframes | BSD-style core plus notices; WebGL; M–L | Genuine new documentary capability. Cache tiles and await readiness; use frame-derived camera states. Map data, tiles, glyphs and imagery have separate availability/attribution terms. |
| P1 [OpenTimelineIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO) | Export editable timeline from canonical edit decisions | Apache-2.0; Python/C++; M | Supports professional handoff. It is an interchange format/API, not a renderer. Begin with native OTIO, then separately test editor adapters and lossy effects conversion. |
| P1 [resvg](https://github.com/linebender/resvg) | Reliable SVG rasterization and thumbnail generation | Apache-2.0/MIT project licensing; Rust/native; S–M | Useful infrastructure for sketch/diagram assets. Not an animation engine. Freeze fonts and reject unsupported features before capture. |
| P2 [Motion Canvas](https://github.com/motion-canvas/motion-canvas) | Code- and narration-oriented explainers with coordinated scenes | Root metadata currently MIT; TypeScript/browser; L | Strong fit creatively, but overlaps our renderers and requires a new authoring/export path. Upstream has discussed GPL migration: inspect exact package/tag licenses before pinning. Use a separate optional adapter if adopted. |
| P2 [Anime.js](https://github.com/juliangarnier/anime) | Alternative JS tween/timeline backend | MIT; browser; M | Useful if an MIT animation backend is a product requirement; otherwise little immediate gain over existing GSAP integration. Keep one scene specification and compile to the approved backend. |
| P2 [Rive runtime](https://github.com/rive-app/rive-runtime) | Playback/state control of pre-authored animated assets | MIT runtime; native/WASM; L | Runtime openness does not establish editor or asset openness. Requires prepared assets and deterministic state/input replay. Defer until there is a specific character or interactive-asset library. |
| P2 [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | Alternative local transcription backend, including Apple hardware paths | MIT; native CPU/accelerated; M | Potential deployment win on Macs. Compare against existing faster-whisper/WhisperX instead of adding a duplicate default. Model files and memory depend on selected model. |
| P1 extension [librosa](https://github.com/librosa/librosa) | Beat/onset/envelope extraction for motion accents | ISC; Python CPU; S–M | Already a dependency of BMTS-lite. Expose its timing results as an artifact and add opt-in beat snapping. Beat detection is uncertain on speech/ambient audio; preserve manual overrides. |
| P1 extension [WhisperX](https://github.com/m-bain/whisperX) | Word alignment and speaker timing for captions | BSD-2-Clause code; Python/models; M | Already referenced by transcriber. Audit installed-version API compatibility and alignment failure handling first. Diarization model access and licenses are separate; CPU throughput must be measured. |
| P1 QA [VMAF](https://github.com/Netflix/vmaf) | Compare delivery encode with a reference render | BSD-2-Clause-Patent; native/FFmpeg integration; S–M | Measures reference-based video degradation. Cannot judge storytelling, typography, factual accuracy, or artistic merit. Pair with structural checks, not a universal quality score. |

## Tools to defer

- [Animated Drawings](https://github.com/facebookresearch/AnimatedDrawings): repository is archived in the current API snapshot; guide already references it. Retain as an optional, pinned compatibility route instead of building a new core dependency.
- [Synfig](https://github.com/Synfig/synfig): GPL-3.0 repository; capable animation application, but another project format and runtime increase integration costs. Revisit for user-supplied Synfig projects.
- [OpenToonz](https://github.com/opentoonz/opentoonz): full 2D animation application; strong artist workflow, weaker first fit for a small-model headless interface. Root API license is unclassified; inspect LICENSE and bundled dependency notices before adoption.
- [MoviePy](https://github.com/Zulko/moviepy): MIT, useful Python editing, but substantial overlap with the existing FFmpeg composition layer. Add only for a demonstrated operation gap.
- React Spring: another spring/tween abstraction brings limited incremental value while adding frame-clock integration work.
- More generative video/3D models: existing provider surface is already broad. Evaluate against a specific missing capability and hardware budget; open code is not sufficient evidence that weights permit intended use.

## Proposed motion coverage

These are our proposed recipe families, not upstream promises of turnkey presets:

1. Vector: path draw/erase, shape-to-shape morph, split/merge, liquid badge, icon transformation.
2. Diagram: node reveal, edge trace, packet flow, branch highlight, graph expansion and relayout.
3. Sketch: hatch reveal, seeded line variation, underline, annotation circle, whiteboard builds.
4. Physics: drop-and-settle, domino chain, pendulum, stack collapse, constrained orbit.
5. Particles: confetti burst, star field, snow, ember drift, particle trail.
6. Characters: mouth-cue playback, blink/gaze controls, existing named mocap actions synchronized to narration.
7. Data: bar growth, line reveal, category highlight, counter changes, ranked transitions.
8. Geography: route trace, location pulse, camera travel and region emphasis.
9. Editing: curated GL transitions with bounded parameters and exact frame progress.

## Architecture for cheap-model reliability

Expose a small capability-oriented surface, not a separate MCP tool for every effect. Proposed tools: `motion_catalog`, `motion_validate`, `motion_preview`; production rendering remains a registered BaseTool operation submitted through normal factory routes. Names here are proposals, not installed tools.

Use a versioned JSON scene contract containing canvas, fps, duration, seed, assets, named objects, recipe cues and theme. Resolve object ids server-side. Each recipe advertises required object types, allowed parameters, timing limits, runtime support and one minimal example. The compiler owns geometry and timing; the agent still owns creative selection and stage orchestration, preserving the project architecture.

Validation should return machine-readable field paths, allowed values and minimal corrections. Reject conflicting cues rather than silently overriding them. Measure font layout and overflow before render. Bound text length, node count, particle count and output duration. Separate unavailable runtime errors from invalid arguments.

A recipe must support the selected renderer explicitly. Do not silently change runtimes. The current GSAP-only helper should report that scope clearly. Keep prepared components within the templated authoring mode; preserve the project's bespoke/atelier rules for hero work.

## Delivery order and acceptance criteria

**Phase 1: contracts and visual fixtures.** Add a complete renderable scene wrapper around the current compiler. Verify start/middle/end frames, delayed entrance visibility, exits, overlapping-property errors, stagger counts, exact duration and reduced motion. Add package/version provenance and runtime health.

**Phase 2: high-value primitives.** Integrate Flubber, Rough.js and a curated GL subset; then ELK and Lottie. Produce one canonical sample scene per recipe, saved as reproducible fixtures. Keep offline assets and fonts pinned.

**Phase 3: narration and expressive motion.** Add Rhubarb, expose existing beat/alignment data, then fixed-step Matter.js and controlled particle playback. Bake simulation state for repeatable random-access renders.

**Phase 4: specialized workflows.** Add maps, OTIO handoff and quality comparisons. Only add another full authoring engine when a benchmark shows a capability gap.

Benchmark the actual inexpensive model on 30 briefs covering titles, diagrams, charts, morphs, characters and mixed scenes, with three runs per brief. Compare current raw authoring against recipe-based authoring at matched output requirements. Record first-call schema validity, total retries, tokens, cost, render completion, duration error, overflow, missing assets, human visual rating and gate violations. Proposed release targets: at least 95% valid first calls, at least 90% successful renders within two repairs, and zero gate violations. These are targets, not observed results. Never equate schema validity with a good video.

## Evidence and limitations

Primary repositories and their README/license files were inspected through web browsing and GitHub API metadata. Root license classifications that returned NOASSERTION were checked directly for ELK, Rhubarb, MapLibre, GL Transitions and VMAF. Push timestamps indicate repository activity, not quality, security, release cadence, or compatibility. No candidate was installed or benchmarked in this research. Pin specific versions and review exact shipped components before implementation.
