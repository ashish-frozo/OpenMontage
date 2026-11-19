---
name: creator-workflow
description: Animatics, locked revisions, sound cues, temporal quality review and portable editorial handoff.
---
# Creator workflow

Use the existing pipeline and approval gates. These tools execute explicit data;
the agent remains responsible for creative decisions.

1. Author scene_plan version 1.1 with stable ids, shot_intent and narrative_role.
   `anime_scene` and per-scene metadata are accepted. Describe recurring entities
   in continuity entries: entity_id, reference_assets, state_in, state_out and
   change_reason when a cut intentionally changes wardrobe, lighting, direction,
   location or product state. These are declarations, not visual proof.
2. Call factory_review_scene_plan. Resolve timing/identity issues and inspect
   continuity warnings. Preserve the returned fingerprint for revisions.
3. In scene_plan, run openmontage:animatic before costly asset generation. Supply
   available storyboard images/video as frames with shot_id/path, optional caption,
   and approved temporary audio in sound_cues. Missing images produce clearly
   provisional text cards. Review the MP4 with its SRT track, then approve the
   scene-plan gate. The animatic does not approve final art or switch final runtime.
4. For a note such as “shorten shot 2; keep its voice”, call factory_revision_plan
   with expected_fingerprint, shot-id changes, and locks such as
   {"shot2":["metadata.voice","continuity"]}. Dot paths must exist. A '*' locks
   an entire shot. set_fields accepts dot paths such as metadata.background to preserve sibling
   values, or complete top-level replacements. Prefer factory_preview_revision
   with project_id so the server holds the original scene plan. Then call
   factory_save_revision to persist the candidate, preserve locks, invalidate
   downstream approvals and saved routes, and require scene-plan review. ripple moves later shots and refuses any
   conflicting timing lock. Record notes and candidate in the next checkpoint.
   Reapprove changed gated stages; do not reuse obsolete routes/final reviews.
   Rerender only reported shot ids. Animatic caches unchanged shots by source bytes
   and parameters; retimed clips reuse picture, while the sequence and mix rebuild.
5. Sound cues have id, role, path (except silence), start, duration, source_start,
   gain, fade_in/out and intent. Schedule dialogue before picture for a J-cut or
   across the next shot for an L-cut. sound_design mixes WAV, ducks non-dialogue
   under narration and measures loudness. Silence cues mute the complete mix.
   Target loudness is configurable; -16 LUFS is a working default, not a universal
   delivery standard. Listen to transitions and speech intelligibility.
6. media_transition blends real image/video sources. It returns picture only;
   account for overlap in duration and compose sound separately. motion_scene now
   accepts media image paths and mouth-image rigs; use local approved assets.
7. creator_quality runs full-stream black/freeze/silence detection, measures audio,
   samples each shot/cut boundary, checks SRT timing and supplied text safe boxes.
   Intentional holds, fades and silence are candidates for review, never automatic
   artistic failures. It cannot establish visual identity, OCR accuracy, caption
   semantics or intelligibility. Inspect samples and listen; create final_review.
8. editor_package writes an immutable directory with relative OTIO links, copied
   sources, separate audio tracks, captions, markers and an unsupported-effects
   report. Provide rendered stems as Audio clips if stems are needed. It does not
   unmix a finished soundtrack or round-trip arbitrary NLE effects.

Keep accessibility captions even when narration repeats a headline. Change the
headline's placement/timing instead. Recurring products, characters and motifs
are allowed; evaluate narrative progression rather than forcing visual novelty.
