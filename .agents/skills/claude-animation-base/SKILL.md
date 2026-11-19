---
name: claude-animation-base
description: Use for hand-painted 2D character animation planning, acting beats, viewer-aware timing, staging, and scene continuity. Adapt the guide to original characters and the selected OpenMontage renderer.
license: MIT
metadata:
  author: John Heibel
  upstream: https://github.com/JohnHeibel/ClaudeAnimationBase
---

# Claude Animation Base: OpenMontage Guide

Read [the upstream animation guide](references/ANIMATION_GUIDE.md) when planning hand-painted character work. It covers acting, anticipation, overlapping action, readable timing, scene links, and self-review.

## Use in OpenMontage

- Treat the guide as animation direction, not as a renderer or an MCP operation.
- Use original or user-provided characters. The upstream Clawd character, its designs, model sheets, and related marks are not included and are not licensed by this skill.
- For deterministic video, derive movement from the current frame/time. Keep a storyboard and follow the pipeline's existing checkpoint and review gates.
- Choose the actual renderer through the project's pipeline and `factory_operations`; this guide does not install p5.js, p5.brush, Chrome, or ffmpeg.
- Adapt the no-text/no-3D constraints only when they suit the approved brief. The upstream guide is a creative reference, not a hard OpenMontage policy.
