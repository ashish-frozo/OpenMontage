"""Fetch an original source into a bounded, timestamped evidence record."""
import json
from pathlib import Path
from pydantic import Field
from content_factory.models import Model
from tools.base_tool import BaseTool, ToolResult, ToolRuntime, ResourceProfile
from lib.research import retrieve
class FetchInput(Model):
    url: str = Field(min_length=10,max_length=2000)
    output_path: str
class ResearchFetch(BaseTool):
    name='research_fetch'
    capability='research'
    runtime=ToolRuntime.API
    provider='public_web'
    resource_profile=ResourceProfile(network_required=True)
    input_schema=FetchInput.model_json_schema()
    agent_skills=['autonomous-content']
    def execute(self,inputs):
        p=FetchInput.model_validate(inputs);source=retrieve(p.url)
        path=Path(p.output_path);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(source,ensure_ascii=False))
        return ToolResult(success=True,data={**source,'output_path':str(path)},artifacts=[str(path)])
