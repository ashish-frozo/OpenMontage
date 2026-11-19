"""Search background knowledge or a configured SearXNG instance for source leads."""
from pydantic import Field
from typing import Literal
from content_factory.models import Model
from tools.base_tool import BaseTool, ToolResult, ToolRuntime, ResourceProfile
from lib.research import search
class SearchInput(Model):
    query: str = Field(min_length=2,max_length=500)
    provider: Literal['wikipedia','searxng','tavily']='wikipedia'
    limit: int = Field(default=5,ge=1,le=10)
class ResearchSearch(BaseTool):
    name='research_search'
    capability='research'
    runtime=ToolRuntime.API
    provider='public_web'
    resource_profile=ResourceProfile(network_required=True)
    input_schema=SearchInput.model_json_schema()
    agent_skills=['autonomous-content']
    def estimate_cost(self,inputs):
        return .02 if inputs.get("provider")=="tavily" else 0.0
    def execute(self,inputs):
        p=SearchInput.model_validate(inputs)
        return ToolResult(success=True,data=search(**p.model_dump()),cost_usd=None if p.provider=="tavily" else 0.0)
