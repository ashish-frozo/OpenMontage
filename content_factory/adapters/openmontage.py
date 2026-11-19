from dataclasses import asdict
import json
from pathlib import Path

from content_factory.models import Operation, PluginManifest
from content_factory.registry import Plugin
from lib.paths import REPO_ROOT


class OpenMontage(Plugin):
    manifest = PluginManifest(id="openmontage", version="1.0.0", description="Existing OpenMontage tool registry and production adapters.", best_for=["footage editing", "generation", "composition", "analysis"])

    def __init__(self):
        from tools.tool_registry import registry
        self.registry = registry

    def operations(self):
        self.registry.ensure_discovered()
        items = []
        for t in (self.registry.get(n) for n in sorted(self.registry.list_all())):
            if t.provider == "lemo":
                continue
            instructions = [f".agents/skills/{s}/SKILL.md" for s in t.agent_skills]
            if t.name == "hyperframes_compose":
                # These two workflow references are used by connected agents
                # in addition to the renderer's own CLI and registry guides.
                instructions.extend([
                    ".agents/skills/hyperframes-core/SKILL.md",
                    ".agents/skills/faceless-explainer/SKILL.md",
                ])
            items.append(Operation(
                id=t.name, capability=t.capability, description=(t.__class__.__doc__ or t.name).strip(),
                provider=t.provider, runtime=t.runtime.value, version=t.version,
                input_schema=t.input_schema or {"type": "object"}, output_schema=t.output_schema,
                best_for=t.best_for, limitations=t.not_good_for, native_tool=t.name,
                instructions=instructions,
            ))
        return items

    def health(self, operation):
        t = self.registry.get(operation)
        return {"status": t.get_status().value, "setup": t.install_instructions,
                "network_required": t.resource_profile.network_required or t.runtime.value in {"api", "hybrid"},
                "resources": asdict(t.resource_profile)}

    def estimate(self, operation, params):
        return self.registry.get(operation).estimate_cost(params)

    def execute(self, operation, params):
        result = self.registry.get(operation).execute(params)
        return asdict(result)

    def instruction(self, name):
        # Accept the legacy instruction names sent by connected clients as
        # well as the canonical skill directory paths published in manifests.
        aliases = {
            "hyperframes-core": ".agents/skills/hyperframes-core/SKILL.md",
            "skills/hyperframes-core.md": ".agents/skills/hyperframes-core/SKILL.md",
            "faceless-explainer": ".agents/skills/faceless-explainer/SKILL.md",
            "skills/faceless-explainer.md": ".agents/skills/faceless-explainer/SKILL.md",
        }
        name = aliases.get(name, name)
        allowed = {p for op in self.operations() for p in op.instructions}
        if name in allowed:
            path = (REPO_ROOT / name).resolve()
            if not path.is_relative_to(REPO_ROOT.resolve()):
                raise ValueError("Instruction outside repository")
            return path.read_text()

        catalog = json.loads((REPO_ROOT / "styles/community/catalog.json").read_text(encoding="utf-8"))
        skill_roots = set()
        for resource in catalog["motion_resources"]:
            for instruction in [resource.get("instruction"), *resource.get("additional_instructions", [])]:
                if instruction and instruction.startswith(".agents/skills/"):
                    skill_roots.add(Path(instruction).parts[:3])
        requested = Path(name)
        if ".." in requested.parts:
            raise ValueError("Instruction path traversal rejected")
        local_skills = REPO_ROOT / ".agents/skills"
        # Skill packs live in their own directories. Allow a referenced skill
        # and its bundled references (including slash-named shared files such
        # as hyperframes-core and workflow packs), never sibling or other repo paths.
        skill_dirs = [p.resolve() for p in local_skills.iterdir() if p.is_dir()]
        allowed_roots = {REPO_ROOT.joinpath(*root).resolve() for root in skill_roots}
        allowed_roots.update(root for root in skill_dirs if root.name in {"hyperframes-core", "faceless-explainer"})
        matched_roots = [root for root in allowed_roots if requested.parts[:2] == (".agents", "skills")
                         and len(requested.parts) >= 3
                         and REPO_ROOT.joinpath(*requested.parts[:3]).resolve() == root]
        if requested.suffix.lower() != ".md" or not matched_roots:
            raise ValueError("Instruction is not declared by this plugin")
        path = (REPO_ROOT / name).resolve()
        if not path.is_file() or not any(path.is_relative_to(root) for root in matched_roots):
            raise ValueError("Instruction outside an installed skill directory")
        return path.read_text()

    def styles(self):
        """Return native OpenMontage playbooks and curated community style recipes."""
        from styles.playbook_loader import list_playbooks, load_playbook

        items = []
        for slug in list_playbooks():
            playbook = load_playbook(slug)
            identity = playbook["identity"]
            items.append({
                "id": slug,
                "name": identity["name"],
                "description": identity.get("best_for", identity["mood"]),
                "category": identity["category"],
                "best_for": identity.get("best_for", ""),
                "source_type": "openmontage_playbook",
                "playbook": f"styles/{slug}.yaml",
                "renderers": ["remotion", "hyperframes", "ffmpeg", "lemo"],
            })
        catalog_path = REPO_ROOT / "styles/community/catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        items.extend(catalog["styles"])
        return sorted(items, key=lambda item: (item["name"].casefold(), item["id"]))

    def style(self, style_id: str):
        """Return the complete playbook or community recipe and its provenance."""
        from styles.playbook_loader import list_playbooks, load_playbook

        if style_id in list_playbooks():
            return {"id": style_id, "source_type": "openmontage_playbook",
                    "playbook": load_playbook(style_id)}
        catalog = json.loads((REPO_ROOT / "styles/community/catalog.json").read_text(encoding="utf-8"))
        for item in catalog["styles"]:
            if item["id"] == style_id:
                return item
        raise ValueError(f"Unknown OpenMontage style: {style_id}")

    def motion_resources(self):
        catalog = json.loads((REPO_ROOT / "styles/community/catalog.json").read_text(encoding="utf-8"))
        return catalog["motion_resources"]
