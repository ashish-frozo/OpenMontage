from content_factory.adapters.openmontage import OpenMontage


def test_hyperframes_core_instruction_is_readable():
    text=OpenMontage().instruction('.agents/skills/hyperframes-core/SKILL.md')
    assert 'hyperframes-core' in text


def test_faceless_explainer_instruction_and_references_are_readable():
    plugin=OpenMontage()
    text=plugin.instruction('.agents/skills/faceless-explainer/SKILL.md')
    assert 'faceless-explainer' in text
    assert plugin.instruction('.agents/skills/faceless-explainer/agents/scriptwriting.md')


def test_arbitrary_instruction_paths_remain_denied():
    import pytest
    plugin=OpenMontage()
    for path in ['.env','.agents/skills/hyperframes-core/../../../../.env',
                 '.agents/skills/openshorts/SKILL.md']:
        with pytest.raises(ValueError):plugin.instruction(path)
