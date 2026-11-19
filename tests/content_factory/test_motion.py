import pytest
from pydantic import ValidationError
from content_factory.motion import PRESETS, MotionPlan, compile_motion


def test_all_presets_compile():
    assert len(PRESETS) == 42
    for preset in PRESETS:
        result = compile_motion(MotionPlan(cues=[dict(preset=preset, target='.title')]))
        assert result['duration_seconds'] > 0
        assert 'tl.fromTo' in result['source']
        assert result['rendered'] is False


def test_timing_and_reduced_motion():
    cues = [dict(preset='pulse', target='.item', at=1, duration=2, stagger=.1, count=3)]
    assert compile_motion(MotionPlan(cues=cues))['duration_seconds'] == 5.2
    result = compile_motion(MotionPlan(cues=cues, reduced_motion=True))
    assert result['duration_seconds'] == 3.2
    assert 'scale' not in result['source']


def test_invalid_inputs():
    with pytest.raises(ValueError, match='Unknown motion'):
        compile_motion(MotionPlan(cues=[dict(preset='invented', target='.title')]))
    for override in [dict(target='</script>'), dict(duration=-1), dict(at=float('nan')), dict(count=0), dict(unknown=True)]:
        with pytest.raises(ValidationError):
            MotionPlan(cues=[dict(preset='fade_in', target='.title') | override])
