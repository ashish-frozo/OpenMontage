"""Local Chatterbox speech with optional reference voice and expressive controls."""
from pathlib import Path
from tools.base_tool import BaseTool, ToolResult, ToolStatus, ToolTier, ToolRuntime, ToolStability, Determinism, ResourceProfile

class ChatterboxTTS(BaseTool):
    name='chatterbox_tts'
    version='1.0.0'
    provider='chatterbox'
    capability='tts'
    tier=ToolTier.VOICE
    runtime=ToolRuntime.LOCAL
    stability=ToolStability.BETA
    determinism=Determinism.SEEDED
    agent_skills=['local-voiceover']
    resource_profile=ResourceProfile(cpu_cores=4,ram_mb=6000,disk_mb=3000,network_required=False)
    install_instructions='Create .venv-chatterbox, install requirements-chatterbox.txt, then run .venv-chatterbox/bin/python scripts/setup_local_tts.py chatterbox. Add --variant multilingual to install that model.'
    best_for=['expressive local narration','reference-voice speech','multilingual narration with optional model']
    not_good_for=['word timestamps','uninstalled languages','guaranteed sample-identical generation across hardware']
    supports={'voice_cloning':True,'offline':True,'multilingual':True}
    input_schema={'type':'object','additionalProperties':False,'required':['text','output_path'],'properties':{
        'text':{'type':'string','minLength':1,'maxLength':1000},
        'output_path':{'type':'string'},
        'variant':{'type':'string','enum':['english','multilingual'],'default':'english'},
        'language_code':{'type':'string','default':'en'},
        'reference_audio_path':{'type':'string','description':'Optional local clean reference speech; omit to use the model default voice.'},
        'exaggeration':{'type':'number','minimum':0,'maximum':2,'default':.5},
        'cfg_weight':{'type':'number','minimum':0,'maximum':1,'default':.5},
        'temperature':{'type':'number','exclusiveMinimum':0,'maximum':2,'default':.8},
        'seed':{'type':'integer','minimum':0,'maximum':2147483647,'default':1},
        'device':{'type':'string','enum':['auto','cpu','mps','cuda'],'default':'auto'}}}
    def get_status(self):
        from lib.local_tts import health
        return ToolStatus(health('chatterbox')['status'])
    def execute(self,inputs):
        import jsonschema
        from lib.local_tts import synthesize
        try:
            jsonschema.validate(inputs,self.input_schema)
            if inputs.get('variant','english')=='english' and inputs.get('language_code','en') not in ('en','en-US','en-GB'):
                raise ValueError('Choose variant=multilingual for non-English speech')
            if inputs.get('reference_audio_path'):
                import wave
                ref=Path(inputs['reference_audio_path']).expanduser().resolve(strict=True)
                if not ref.is_file(): raise ValueError('Reference audio file missing')
                from lib.creator_media import probe
                info=probe(ref);duration=float(info['format']['duration'])
                if not 3<=duration<=30 or not any(s['codec_type']=='audio' for s in info['streams']): raise ValueError('Use a clean 3–30 second reference recording')
                inputs={**inputs,'reference_audio_path':str(ref)}
        except (ValueError,OSError,jsonschema.ValidationError) as exc: return ToolResult(success=False,error=str(exc))
        return synthesize('chatterbox',inputs)
