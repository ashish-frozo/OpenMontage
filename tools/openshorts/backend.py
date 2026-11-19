"""OpenShorts clipping, captioning and agent-directed recuts through its self-hosted MCP API."""
from abc import abstractmethod
import json
import math
import os
from pathlib import Path
from urllib.parse import urlsplit
import httpx
import jsonschema
from tools.base_tool import BaseTool, ToolResult, ToolRuntime, ToolStatus, ResourceProfile


def endpoint():
    # Administrator configuration only; callers cannot select arbitrary endpoints.
    url = os.environ.get('OPENSHORTS_API_URL', '').rstrip('/')
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError('Configure OPENSHORTS_API_URL with the self-hosted service base URL')
    if p.scheme == 'http' and p.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Remote OpenShorts services require HTTPS')
    return url + '/mcp'


class _OpenShorts(BaseTool):
    runtime = ToolRuntime.API
    provider = 'openshorts'
    resource_profile = ResourceProfile(network_required=True)
    agent_skills = ['openshorts']
    best_for = ['long video to vertical shorts', 'face tracking', 'styled captions', 'agent-directed clip recuts']
    not_good_for = ['original motion graphics', 'automatic publication', 'guaranteed viral results']
    install_instructions = 'Run the self-hosted OpenShorts backend; configure OPENSHORTS_API_URL. See docs/content-factory/openshorts.md.'

    @property
    @abstractmethod
    def operation(self): ...

    def get_status(self):
        try:
            url = endpoint().removesuffix('/mcp') + '/health/ready'
            with httpx.Client(timeout=2, follow_redirects=False, trust_env=False) as client:
                response = client.get(url)
                response.raise_for_status()
            return ToolStatus.AVAILABLE
        except (ValueError, httpx.HTTPError):
            return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs):
        value = float(inputs.get('estimated_cost_usd', 0))
        if not math.isfinite(value) or value < 0:
            raise ValueError('estimated_cost_usd must be finite and nonnegative')
        return value

    def execute(self, inputs):
        jsonschema.validate(inputs, self.input_schema)
        self.estimate_cost(inputs)
        params = {k: v for k, v in inputs.items() if k != 'estimated_cost_usd'}
        vertical_layout = params.pop('vertical_layout', None)
        if vertical_layout is not None:
            if 'framing' in params:
                raise ValueError('Use either vertical_layout or framing, not both')
            params['framing'] = {'fill': 'track', 'fit': 'full', 'auto': 'auto'}[vertical_layout]
        headers = {}
        key = os.environ.get('OPENSHORTS_API_KEY', '').strip()
        if key:
            headers['Authorization'] = 'Bearer ' + key
        try:
            # One bounded call. Never replay a timed-out submission or mutation.
            with httpx.Client(timeout=180 if self.operation in ('recut_clip', 'add_subtitles') else 45, follow_redirects=False, trust_env=False) as client:
                r = client.post(endpoint(), headers=headers, json={
                    'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': self.operation, 'arguments': params}})
                r.raise_for_status()
                data = r.json()
            if 'error' in data:
                return ToolResult(success=False, error='OpenShorts rejected the MCP request; inspect backend logs.')
            result = data['result']
            return ToolResult(success=not result.get('isError', False), data={
                'upstream_result': result,
                'note': ('A submission response is not a completed render. Save its upstream job_id and poll get_job_status.' if self.operation == 'process_video' else 'Inspect upstream_result for the operation result and clip links.')},
                error='OpenShorts operation failed; inspect upstream_result.' if result.get('isError') else None,
                cost_usd=None if self.operation in ('process_video','add_subtitles','recut_clip') else 0)
        except (httpx.HTTPError, ValueError, KeyError):
            return ToolResult(success=False, error='OpenShorts transport failed. A write may have been accepted: inspect the backend before resubmitting; no automatic retry was made.')


for _spec in json.loads(Path(__file__).with_name('operations.json').read_text()):
    _op = _spec['name']
    globals()['OpenShorts' + ''.join(x.title() for x in _op.split('_'))] = type(
        'OpenShorts' + ''.join(x.title() for x in _op.split('_')), (_OpenShorts,), {
            '__module__': __name__, '__doc__': _spec['description'],
            'name': 'openshorts_' + _op, 'operation': _op,
            'capability': 'video_clipping' if _op == 'process_video' else 'clip_editing',
            'input_schema': _spec['inputSchema']})
