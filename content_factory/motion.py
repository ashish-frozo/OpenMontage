"""Deterministic motion authoring helpers; no rendering or orchestration."""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PRESETS: dict[str, dict] = {}


def _add(name, start, end, category='entrance', ease='power2.out'):
    PRESETS[name] = dict(id=name, category=category, start=start, end=end, ease=ease)


_add('fade_in', {'opacity': 0}, {'opacity': 1})
_add('fade_out', {'opacity': 1}, {'opacity': 0}, 'exit')
for direction, axis, distance in [('left', 'x', -80), ('right', 'x', 80), ('up', 'y', -80), ('down', 'y', 80)]:
    _add('slide_in_' + direction, {axis: distance, 'opacity': 0}, {axis: 0, 'opacity': 1})
    _add('slide_out_' + direction, {axis: 0, 'opacity': 1}, {axis: distance, 'opacity': 0}, 'exit')
    _add('bounce_in_' + direction, {axis: distance, 'opacity': 0}, {axis: 0, 'opacity': 1}, ease='bounce.out')
    _add('elastic_in_' + direction, {axis: distance, 'opacity': 0}, {axis: 0, 'opacity': 1}, ease='elastic.out(1,0.4)')
for name, scale, ease in [('zoom', 0.5, 'power2.out'), ('pop', 0, 'back.out(1.7)'), ('shrink', 1.5, 'power2.out')]:
    _add(name + '_in', {'scale': scale, 'opacity': 0}, {'scale': 1, 'opacity': 1}, ease=ease)
    _add(name + '_out', {'scale': 1, 'opacity': 1}, {'scale': scale, 'opacity': 0}, 'exit')
for axis in ['X', 'Y']:
    _add('flip_in_' + axis.lower(), {'rotation' + axis: 90, 'opacity': 0}, {'rotation' + axis: 0, 'opacity': 1})
    _add('flip_out_' + axis.lower(), {'rotation' + axis: 0, 'opacity': 1}, {'rotation' + axis: 90, 'opacity': 0}, 'exit')
_add('spin_in', {'rotation': -180, 'scale': 0, 'opacity': 0}, {'rotation': 0, 'scale': 1, 'opacity': 1})
_add('spin_out', {'rotation': 0, 'scale': 1, 'opacity': 1}, {'rotation': 180, 'scale': 0, 'opacity': 0}, 'exit')
for name, inset in [('left', '0 100% 0 0'), ('right', '0 0 0 100%'), ('up', '0 0 100% 0'), ('down', '100% 0 0 0')]:
    _add('wipe_in_' + name, {'clipPath': f'inset({inset})'}, {'clipPath': 'inset(0% 0% 0% 0%)'})
    _add('wipe_out_' + name, {'clipPath': 'inset(0% 0% 0% 0%)'}, {'clipPath': f'inset({inset})'}, 'exit')
for name, end in [('pulse', {'scale': 1.08}), ('float', {'y': -15}), ('wiggle', {'rotation': 5}), ('nudge', {'x': 12})]:
    _add(name, {key: 1 if key == 'scale' else 0 for key in end}, end, 'emphasis', 'sine.inOut')


class MotionCue(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    preset: str = Field(description='Exact id from factory_motion_presets.')
    target: str = Field(pattern=r'^[.#][A-Za-z_][A-Za-z0-9_-]{0,79}$', description='Simple CSS class or id, e.g. .headline.')
    at: float = Field(default=0, ge=0, le=600)
    duration: float = Field(default=0.6, ge=0.05, le=30)
    stagger: float = Field(default=0, ge=0, le=2)
    count: int = Field(default=1, ge=1, le=100, description='Expected matching elements; used for duration accounting.')


class MotionPlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    cues: list[MotionCue] = Field(min_length=1, max_length=100)
    reduced_motion: bool = False


def compile_motion(plan: MotionPlan) -> dict:
    """Return a reusable function accepting GSAP and an existing paused timeline."""
    steps = []
    duration = 0.0
    for cue in plan.cues:
        if cue.preset not in PRESETS:
            raise ValueError(f'Unknown motion {cue.preset!r}; call factory_motion_presets for supported ids.')
        preset = deepcopy(PRESETS[cue.preset])
        start, end = preset['start'], preset['end']
        if plan.reduced_motion:
            start = {'opacity': 1 if preset['category'] == 'exit' else 0}
            end = {'opacity': 0 if preset['category'] == 'exit' else 1}
        end.update(duration=cue.duration, stagger=cue.stagger, ease=preset['ease'], immediateRender=False)
        if preset['category'] == 'emphasis' and not plan.reduced_motion:
            end.update(repeat=1, yoyo=True)
        duration = max(duration, cue.at + cue.duration * (2 if end.get('yoyo') else 1) + cue.stagger * (cue.count - 1))
        steps.append(f'  tl.fromTo({json.dumps(cue.target)}, {json.dumps(start)}, {json.dumps(end)}, {cue.at});')
    return {'runtime': 'gsap', 'source': 'function applyMotion(tl) {\n' + '\n'.join(steps) + '\n  return tl;\n}',
            'duration_seconds': duration, 'preset_count': len(plan.cues),
            'requirements': ['GSAP 3 loaded by the host workspace', 'Matching DOM elements exist before applyMotion(tl)',
                             'Use a paused timeline and seek it for deterministic frame capture',
                             'count must match DOM targets for accurate duration; avoid overlapping cues on the same properties'],
            'rendered': False}
