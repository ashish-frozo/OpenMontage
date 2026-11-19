# Lemo in OpenMontage

Use the animation pipeline. Read its current stage director, then the installed
Lemo DIRECTOR.md, TECHNIQUE.md, core/README.md and chosen STYLE.md. Author a fresh
scene from the brief; do not reuse finished demo compositions as templates.

Lemo is an asset renderer here: create clips during assets, then use the approved
OpenMontage composition runtime for the final edit, narration and mix. Do not
set edit_decisions.render_runtime to lemo (it is not a supported final runtime).
Keep the authored workspace and every output inside projects/<project-id>/.
Write clips and provenance into the canonical asset_manifest before completing
assets. Use previews and readability checks before a full render. The calling
AI writes the deterministic page; the MCP server does not generate scene code.

Self-host page assets for offline production. Inspect runtime requirements in the
installed checkout. Keep its revision pinned; do not run automatic setup/update
scripts during production. All normal checkpoint and user approval gates apply.
