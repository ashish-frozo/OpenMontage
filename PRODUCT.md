# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Next.js App Router on Vercel; Supabase Auth, Postgres, and private Storage.

## Users

Independent creators planning and producing videos for YouTube and Instagram.

## Product Purpose

OpenMontage helps a creator move from a researched idea to an editable, reviewable video and a platform-ready export. Success means a creator can get from a brief to a trustworthy draft without installing the production toolchain or losing control of creative approvals.

## Positioning

An open-source, model-agnostic MCP production engine paired with a hosted workspace that adds secure projects, research, approvals, reliable production jobs, and media delivery. The self-hosted engine remains available to creators who want to run their own infrastructure.

## Operating Context

Creators work from a topic or source, research it, shape a story and scene plan, generate or source media and narration, review stages, and export a horizontal or vertical video for YouTube or Instagram. Current production pipelines require external model providers and local render tools; the hosted product must remove that setup burden over time.

## Capabilities and Constraints

- Confirmed first audiences are independent creators and confirmed initial platforms are YouTube and Instagram.
- Research is part of the intended automatic content workflow.
- Script and scene-plan review remain human checkpoints; generation or publishing is not implied by an approved brief.
- The open-source MCP remains self-hostable. The hosted Studio is the paid product direction.
- Studio deployment target is Vercel with Supabase.
- The current repository has a local production engine and Backlot, not a provisioned hosted production worker or live SaaS database.
- Pricing, public signup policy, auto-publishing, and hosted model credits remain open decisions.

## Evidence on Hand

The repository contains the OpenMontage MCP and video production pipelines, plus prior local video and narration workflows. It does not yet contain public customer results, a deployed Studio, or verified SaaS operating metrics. Do not invent testimonials, performance claims, or pricing.

## Product Principles

- Research sources should be visible and revisable.
- Creative approvals are explicit and separate from job execution.
- Provider choice and expected cost are visible before consequential generation.
- Customer work and credentials are isolated by workspace.
- A creator can export their work and choose self-hosted production.
