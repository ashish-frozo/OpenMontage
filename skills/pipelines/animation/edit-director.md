# Edit Director - Animation Pipeline

## When To Use

This stage turns the scene plan into an animatic-grade edit plan. Timing is the product.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/edit_decisions.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["assets"]["asset_manifest"]`, `state.artifacts["scene_plan"]["scene_plan"]`, `state.artifacts["script"]["script"]` | Assets, timing plan, and beats |
| Playbook | Active style playbook | Motion and typography rules |

## Process

### 1. Protect Hold Time

After key reveals, plan enough time for the viewer to process the frame. Do not stack every scene edge to edge with motion.

### 2. Stagger Secondary Elements

Primary element first, supporting elements second. The edit decisions should reinforce hierarchy.

### 3. Keep Motion Meaningful

Motion should signal:

- emphasis,
- transition,
- transformation,
- contrast.

### 4. Use Metadata For Timing Detail

Recommended metadata keys:

- `hold_windows`
- `stagger_rules`
- `transition_map`
- `scene_timing_notes`

### 5. Quality Gate

- key information has enough dwell time,
- movement clarifies hierarchy,
- transitions stay consistent,
- the edit remains readable on the target platform.

## Common Pitfalls

- Overcrowding the timeline with continuous motion.
- Revealing all elements at once.
- Letting stylistic motion reduce readability.

## Creator workflow contract
Read `.agents/skills/creator-workflow/SKILL.md`. New scene plans use version 1.1,
stable ids, shot_intent, narrative_role and declared continuity. Before costly
assets, render and review a playable animatic with temporary approved audio.
Record the animatic path and review in scene-plan metadata before requesting
scene-plan approval. Use factory_revision_plan for timestamped changes and locks;
reapprove revisions and regenerate only affected shots. At compose, run
creator_quality, inspect all shot boundaries and listen to the soundtrack. Its
report is evidence for final_review, not automatic creative approval. Preserve
accessibility captions and intentional recurring subjects. For editor delivery,
use editor_package with separate audio tracks and explicit unsupported effects.
