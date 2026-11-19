"""Inspect the whole timeline and extract every shot boundary for human review."""
import json
import re
import tempfile
import uuid
from pathlib import Path
from pydantic import Field
from lib.creator import Strict, review_scene_plan
from lib.creator_media import probe, run, media_file, loudness
from tools.base_tool import BaseTool, ToolResult

class TextBox(Strict):
    id: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)

class QualityInput(Strict):
    path: str
    scene_plan: dict
    output_path: str
    captions_path: str | None = None
    text_boxes: list[TextBox] = Field(default_factory=list,max_length=1000)
    reference_text: str | None = Field(default=None,max_length=50000)
    transcript_path: str | None = None
    max_word_error_rate: float = Field(default=0.15,ge=0,le=1)
    ocr: bool = False
    safe_margin: float = Field(default=0.05,ge=0,le=0.25)

class CreatorQuality(BaseTool):
    name='creator_quality'
    capability='video_analysis'
    dependencies=['cmd:ffmpeg','cmd:ffprobe']
    input_schema=QualityInput.model_json_schema()
    best_for=['shot-boundary review','black/frozen-frame detection','caption timing','audio measurement']
    agent_skills=['creator-workflow']
    def execute(self, inputs):
        p=QualityInput.model_validate(inputs);source=media_file(p.path);plan=review_scene_plan(p.scene_plan)
        info=probe(source);video=next(s for s in info['streams'] if s['codec_type']=='video');duration=float(info['format']['duration'])
        if not 0<duration<=3600 or len(p.scene_plan['scenes'])>200: raise ValueError('QC limit: 3600 seconds and 200 shots')
        out=Path(p.output_path).resolve()
        if out.suffix!='.json': raise ValueError('Quality report output must be .json')
        out.parent.mkdir(parents=True,exist_ok=True);frames=out.parent/('qc-'+uuid.uuid4().hex);frames.mkdir()
        rate=video.get('avg_frame_rate','24/1').split('/');fps=float(rate[0])/float(rate[1]) if float(rate[1]) else 24
        epsilon=1/max(1,fps);times=set();issues=list(plan['issues'])
        if abs(duration-plan['duration'])>max(epsilon*2,0.1): issues.append({'kind':'duration_mismatch','planned':plan['duration'],'actual':duration})
        for shot in p.scene_plan['scenes']:
            a,b=shot['start_seconds'],shot['end_seconds']
            times.update([max(0,a-epsilon),a,(a+b)/2,max(a,b-epsilon)])
        samples=[]
        for i,t in enumerate(sorted(t for t in times if t<duration)):
            image=frames/f'{i:04d}.jpg'
            run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(source),'-frames:v','1','-vf','scale=640:-2',str(image)],30)
            if image.exists(): samples.append({'time':t,'path':str(image)})
        detection=run(['ffmpeg','-hide_banner','-i',str(source),'-an','-vf','blackdetect=d=0.08:pix_th=0.10,freezedetect=n=-50dB:d=0.75','-f','null','-'])
        events=[line.strip() for line in detection.stderr.splitlines() if re.search(r'black_start:|freeze_(start|end|duration):',line)]
        if events: issues.append({'kind':'temporal_candidates','events':events,'note':'Intentional holds, fades and black frames require human adjudication.'})
        caption_report=[];caption_text=[]
        if p.captions_path:
            text=media_file(p.captions_path).read_text(encoding='utf-8-sig')
            def seconds(v):
                h,m,s=v.replace(',','.').split(':');return int(h)*3600+int(m)*60+float(s)
            previous_end=0
            for block in re.split(r'\n\s*\n',text.strip()):
                match=re.search(r'(\d+:\d\d:\d\d[,.]\d{3})\s*-->\s*(\d+:\d\d:\d\d[,.]\d{3})',block)
                if not match:
                    issues.append({'kind':'invalid_caption_block'});continue
                a,b=map(seconds,match.groups());body=block[match.end():].strip();cps=len(body)/max(.001,b-a)
                caption_report.append({'start':a,'end':b,'characters_per_second':cps})
                caption_text.append(re.sub(r'<[^>]+>','',body))
                if b<=a or b>duration+.05 or a<previous_end: issues.append({'kind':'caption_timing','start':a,'end':b})
                if cps>20: issues.append({'kind':'caption_reading_speed','start':a,'characters_per_second':cps})
                previous_end=b
        for box in p.text_boxes:
            w,h=video['width'],video['height'];mx,my=w*p.safe_margin,h*p.safe_margin
            if box.end<=box.start or box.end>duration: issues.append({'kind':'text_timing','id':box.id})
            if box.x<mx or box.y<my or box.x+box.width>w-mx or box.y+box.height>h-my:
                issues.append({'kind':'text_safe_area','id':box.id})
        caption_accuracy=None
        if p.reference_text and p.captions_path:
            from lib.speech_review import compare_speech
            caption_accuracy=compare_speech(p.reference_text,' '.join(caption_text))
            if caption_accuracy['word_error_rate']>p.max_word_error_rate: issues.append({'kind':'caption_text_mismatch',**caption_accuracy})
        speech=None;ocr_results=[]
        if p.reference_text:
            if not p.transcript_path: issues.append({'kind':'missing_transcript'})
            else:
                from lib.speech_review import compare_speech
                transcript=json.loads(media_file(p.transcript_path).read_text())
                recognized=' '.join(s.get('text','') for s in transcript.get('segments',[]))
                speech=compare_speech(p.reference_text,recognized)
                if speech['word_error_rate']>p.max_word_error_rate: issues.append({'kind':'speech_mismatch',**speech})
        if p.ocr:
            import shutil,subprocess,csv,io
            if not shutil.which('tesseract'): issues.append({'kind':'ocr_unavailable'})
            else:
                for sample in samples:
                    result=subprocess.run(['tesseract',sample['path'],'stdout','tsv'],capture_output=True,text=True,timeout=30,check=True)
                    boxes=[r for r in csv.DictReader(io.StringIO(result.stdout),delimiter='\t') if r.get('text','').strip()]
                    ocr_results.append({'time':sample['time'],'words':boxes})
                    if any(float(r.get('conf',0))<50 for r in boxes): issues.append({'kind':'ocr_low_confidence','time':sample['time']})
        audio=any(s['codec_type']=='audio' for s in info['streams'])
        measured=loudness(source) if audio else None
        if audio:
            silence=run(['ffmpeg','-hide_banner','-i',str(source),'-vn','-af','silencedetect=n=-45dB:d=0.5','-f','null','-'])
            audio_events=[l.strip() for l in silence.stderr.splitlines() if 'silence_start:' in l or 'silence_end:' in l]
            if audio_events: issues.append({'kind':'silence_candidates','events':audio_events})
        from content_factory.workflow import digest
        report={'source_sha256':digest(source),'source_path':str(source),'status':'needs_human_review','technical_probe':info,'samples':samples,'issues':issues,'measured_loudness':measured,'captions':caption_report,
                'speech_comparison':speech,'caption_comparison':caption_accuracy,'ocr_samples':ocr_results,
                'coverage':{'temporal_detection':'entire video','visual_samples':'shot midpoints and cut boundaries','text_safe_area':'caller-supplied boxes only'},
                'human_checks_required':['story and pacing','visual identity and continuity','subtitle accuracy/contrast/collisions','audio transitions and intelligibility','adjudicate intentional holds, black frames and silence']}
        temporary=out.with_name(out.name+'.'+uuid.uuid4().hex+'.tmp');temporary.write_text(json.dumps(report,indent=2));temporary.replace(out)
        return ToolResult(success=True,data={'output_path':str(out),'frames_directory':str(frames),'sample_count':len(samples),'issues':issues,'status':report['status']},artifacts=[str(out),str(frames)])
