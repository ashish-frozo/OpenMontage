# Automatic content workflows

The factory now exposes an evidence-first workflow alongside its existing
pipeline, routing and creator tools. The calling model remains the director.
An optional OpenRouter client runs that agent loop; the MCP itself does not hide
a second LLM or invent creative decisions.

## Workflow

1. Create a project with `max_project_estimate_usd` and the normal production
   preferences. Save explicit preauthorization with
   `factory_save_automation_policy`: stages, operations, expiry, repair limit,
   publishing platforms and exact connected accounts. `creative_discretion` explicitly permits automatic concept selection within the brief. Both automation and creative discretion default to disabled.
   Setting up an integration does not authorize publishing content.
2. `factory_next_action` gives a compact resume point. Read stage instructions
   and native schemas. `research_search` supports Wikipedia, configured HTTPS
   SearXNG, and connected Tavily through Composio (basic search depth). Deep
   research is a multi-query/source-comparison workflow, not a claim that the
   managed Tavily account supports advanced depth.
3. Fetch original sources with `research_fetch`, then save evidence with
   `factory_save_evidence`. Quotes must exist in retrieved text. Store conflicting
   evidence, review semantic support and set a freshness deadline. Unknown source
   dates stay unknown. Search snippets alone cannot become verified evidence.
4. Save canonical research/script/scene artifacts. `factory_audit_script` checks
   claim references, freshness, pronunciation substitutions and duration estimates.
   Automatic script completion requires an audit of the exact canonical sections.
5. Generate actual narration, transcribe it, and use `factory_narration_timeline`
   for measured shot durations and supplied word timestamps. Keep original caption
   spelling; apply pronunciation replacements only to the spoken text.
6. Reuse approved, hash-verified licensed assets. Render through the approved
   pipeline. `creator_quality` now supports transcript comparison and optional
   Tesseract OCR in addition to full-stream technical checks. Visual relevance,
   identity and artistic judgment still require a capable reviewing agent or human.
7. Save a final quality review bound to the exact video hash and technical report.
   Repairs are bounded and preserve locks; authorized scene repairs can retain
   the policy within its repair limit. Actual configuration/profile changes
   invalidate authorization. Download samples/finals with `factory_export_media`.
8. Prepare separate reviewed YouTube/Instagram deliveries. A scheduler executes
   due items only with current account-scoped authorization. Instagram container
   creation, polling and publication have separate durable states. An uncertain
   write never automatically retries. Verify remote delivery and collect analytics
   for the next research brief.

## Runner

Run from the repository's core Python environment:

```sh
.venv/bin/python scripts/run_factory_agent.py \
  --project PROJECT_ID --model OPENROUTER_MODEL_ID \
  --state projects/PROJECT_ID/artifacts/agent-journal.sqlite3 \
  --max-turns 40 --max-minutes 30 --reserve-per-turn 0.02
```

The project and saved policy must already exist. OpenRouter credentials are read
from `OPENROUTER_API_KEY` or `~/.config/openrouter/api-key`, never from prompts.
Use `--remote-config ~/.config/content-factory/remote.json` on the server host to
connect through authenticated remote MCP (needed for Instagram signed media).
The journal records requests before execution. A crash during an uncertain model
or tool call stops replay; inspect the journal and provider state before recovery.
The runner does not fabricate semantic review when its model cannot inspect media.
A text-only model may therefore stop at visual/audio review.

Run queued operations and scheduled delivery without running another LLM:

```sh
.venv/bin/python scripts/factory_scheduler.py --once \
  --remote-config ~/.config/content-factory/remote.json
```

Omit `--once` for a persistent dispatcher; supervise it with launchd/systemd.
It performs no creative planning, grants no authorization and does not replay
uncertain writes. Scheduling requires the dispatcher to remain running.

## Publication adapters

The host uses the authenticated Composio CLI (0.6.1 verified at implementation).
YouTube uploads accept a local video and requested privacy. Instagram uses a
scoped one-hour media URL from the remote server so Meta can fetch the video.
The MCP's interactive download URLs still expire after five minutes.
Account selections are pinned in the policy; no credentials are stored in project
artifacts. Upload responses with unknown outcomes require reconciliation.

`factory_verify_delivery` checks remote identity/metadata and stores a receipt.
`factory_reconcile_delivery` resolves an uncertain delivery using an
operator-verified remote id, without posting again. `factory_collect_performance`
stores YouTube windowed analytics or Instagram lifetime Reel insights; these
metrics must not be compared as if their windows/definitions were identical.

## Limits and operational truth

- Budgets conservatively reserve estimates and retain unknown charges. They are
  not a hard cap on a third-party provider's eventual invoice.
- General web retrieval supports bounded public HTTPS text/HTML/JSON, not PDFs,
  authenticated pages or pages that require JavaScript. Use an appropriate
  extractor for those sources; do not invent missing text.
- Quote matching proves provenance, not truth. ASR/OCR mismatches are review
  candidates, not proof that a video is bad. Semantic assessments are explicit.
- Platform APIs impose account, permissions, upload and analytics constraints.
  An installed connector is not proof a particular account can publish.
- No real content is published by tests. Publishing lifecycle tests mock remote
  writes; a production posting test requires a user-authorized delivery.
- The current deployment is single-owner, not an isolated multi-tenant service.

Provider contracts were inspected through Composio's installed tool schemas.
Background-search protocol: https://www.mediawiki.org/wiki/API:Search.

For the Mac mini installation, the per-user launchd service
`ai.frozo.content-factory.scheduler` runs the dispatcher. Its installer is
`scripts/install_factory_scheduler.py --start`. Only explicitly authorized
projects and deliveries are eligible; installing it does not authorize posting.
CPU transcription dependencies are pinned in `requirements-automation.txt`.
