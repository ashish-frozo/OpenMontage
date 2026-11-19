"""Versioned plugin, configuration and routing contracts."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PluginManifest(Model):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    version: str
    plugin_api_version: Literal[1] = 1
    description: str
    best_for: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class Operation(Model):
    id: str
    capability: str
    description: str
    provider: str
    runtime: str
    version: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] = Field(default_factory=dict)
    best_for: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    input_artifacts: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)
    native_tool: str | None = None


class Routing(Model):
    mode: Literal["auto", "directed", "mixed"] = "auto"
    allowed_plugins: list[str] = Field(default_factory=list, description="Empty permits every installed plugin.")
    excluded_plugins: list[str] = Field(default_factory=list)
    preferred_plugins: list[str] = Field(default_factory=list, description="Soft preferences, not mandatory choices.")
    pinned_operations: dict[str, str] = Field(default_factory=dict, description="Stage -> plugin:operation; hard constraint.")
    local_only: bool = False
    allow_network: bool = True
    priorities: list[str] = Field(default_factory=lambda: ["quality", "cost", "latency"], description="Creative priorities for the calling AI, not numeric quality guarantees.")


class BrandIdentity(Model):
    brand_name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    target_audience: list[str] = Field(default_factory=list, max_length=30)
    voice: list[str] = Field(default_factory=list, max_length=30, description="Voice traits such as clear, expert, warm, or playful.")
    tone: list[str] = Field(default_factory=list, max_length=30)
    visual_style: str = Field(default="", max_length=2000)
    colors: list[str] = Field(default_factory=list, max_length=20)
    fonts: list[str] = Field(default_factory=list, max_length=20)
    logo_asset_ids: list[str] = Field(default_factory=list, max_length=50)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=100)
    avoid: list[str] = Field(default_factory=list, max_length=100, description="Brand elements, language, and visual treatments to avoid.")


class PublishingDefaults(Model):
    platforms: list[str] = Field(default_factory=list, max_length=20)
    aspect_ratio: str | None = Field(default=None, max_length=20, description="Preferred output ratio, e.g. 9:16, 16:9, or 1:1.")
    duration_seconds: int | None = Field(default=None, ge=1, le=3600)
    language: str = Field(default="en", pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$", max_length=35, description="Backwards-compatible default locale (BCP-47 language tag).")
    source_language: str = Field(default="auto", pattern=r"^(?:auto|[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)$", max_length=35, description="Source content language as a BCP-47 tag, or auto for detection.")
    target_languages: list[str] = Field(default_factory=list, max_length=20, description="Target BCP-47 locales. Empty keeps the legacy single publishing language field as the target.")
    caption_languages: list[str] = Field(default_factory=list, max_length=20, description="Caption locales; empty follows target_languages or language.")
    localization_mode: Literal["subtitles", "voiceover", "dubbing", "multi_variant"] = Field(default="subtitles", description="Preferred localization deliverable for each target locale.")
    voice_preferences: dict[str, dict[str, Any]] = Field(default_factory=dict, description="Locale -> provider-specific voice preferences, e.g. {\"es-ES\": {\"provider\": \"kokoro\", \"voice\": \"ef_dora\"}}.")
    captions: bool = True
    caption_style: str = Field(default="", max_length=1000)
    accessibility_notes: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("target_languages", "caption_languages")
    @classmethod
    def validate_locale_tags(cls, values: list[str]) -> list[str]:
        import re
        pattern = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
        if any(not pattern.fullmatch(value) for value in values):
            raise ValueError("Locales must use BCP-47 style tags, for example en, hi-IN, or zh-Hans-CN.")
        return values


class ProductionPreferences(Model):
    allowed_plugins: list[str] = Field(default_factory=list, max_length=50, description="When set, only these plugins may be used.")
    preferred_plugins: list[str] = Field(default_factory=list, max_length=50)
    excluded_plugins: list[str] = Field(default_factory=list, max_length=50)
    preferred_operations: list[str] = Field(default_factory=list, max_length=100)
    allowed_operations: list[str] = Field(default_factory=list, max_length=100, description="When set, only these plugin:operation identifiers may be used.")
    excluded_operations: list[str] = Field(default_factory=list, max_length=100)
    operation_defaults: dict[str, dict[str, Any]] = Field(default_factory=dict, description="Soft native parameter defaults by plugin:operation; project and route choices may override these.")
    priorities: list[str] = Field(default_factory=lambda: ["quality", "brand_fit", "cost", "latency"], max_length=20)
    local_only: bool = False
    allow_network: bool = True
    max_estimated_cost_usd: float | None = Field(default=None, ge=0)
    require_job_approval: bool = True


class SafetyPreferences(Model):
    restricted_topics: list[str] = Field(default_factory=list, max_length=100)
    required_disclaimers: list[str] = Field(default_factory=list, max_length=50)
    claims_require_sources: bool = False
    allowed_asset_sources: list[str] = Field(default_factory=list, max_length=50)
    human_review_required: bool = True


class CustomerProfile(Model):
    name: str = Field(min_length=1, max_length=120)
    brand: BrandIdentity
    publishing: PublishingDefaults = Field(default_factory=PublishingDefaults)
    production: ProductionPreferences = Field(default_factory=ProductionPreferences)
    safety: SafetyPreferences = Field(default_factory=SafetyPreferences)
    custom_guidance: list[str] = Field(default_factory=list, max_length=100)


class ProjectConfig(Model):
    customer_profile_id: str | None = Field(default=None, description="Saved customer profile applied to this project. Its current revision is pinned into each validated route.")
    routing: Routing = Field(default_factory=Routing)
    brief: dict[str, Any] = Field(default_factory=dict, description="AI planning preferences: audience, brand, platform, language, style, duration, etc. Not automatically passed to renderers.")
    native_defaults: dict[str, dict[str, Any]] = Field(default_factory=dict, description="plugin:operation -> native arguments, validated against the operation schema.")
    locked_params: dict[str, dict[str, Any]] = Field(default_factory=dict, description="plugin:operation -> mandatory native values, e.g. model, voice, seed, codec or render_runtime. Steps cannot override these.")
    timeout_seconds: int = Field(default=1800, ge=1, le=86400)
    max_concurrent_jobs: int = Field(default=2, ge=1, le=32)
    max_job_estimate_usd: float | None = Field(default=None, ge=0, description="Reject estimates above this limit. Estimates are not a provider billing cap.")
    max_project_estimate_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False, description="Cumulative conservative budget including job reservations and external agent costs.")
    require_job_approval: bool = True


class RouteStep(Model):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    stage: str
    operation: str = Field(description="plugin:operation identifier")
    params: dict[str, Any] = Field(default_factory=dict, description="Complete native operation parameters; override project defaults.")
    depends_on: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, description="AI explanation tied to the brief and alternatives.")


class RoutePlan(Model):
    request: str = Field(min_length=1)
    steps: list[RouteStep] = Field(min_length=1)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)


class Page(Model):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=30, ge=1, le=100)


def paginate(items: list, page: Page) -> dict:
    end = page.offset + page.limit
    return {"items": items[page.offset:end], "total": len(items), "has_more": end < len(items), "next_offset": end if end < len(items) else None}
