import asyncio
import base64
import json
from pathlib import Path
from unittest.mock import patch

from content_factory.models import CustomerProfile, Page
from content_factory.registry import Registry
from content_factory.service import Factory
from content_factory.remote import AuthDiagnostics, DownloadSigner
from lib.motion_scene import validate_scene
from tools.video.lemo_render import LemoRender
from tools.base_tool import ToolStatus
from tools.graphics.motion_scene import MotionScene


def test_profile_and_history_second_page(tmp_path):
 f=Factory(Registry([]),tmp_path)
 p=CustomerProfile(name='Test',brand={'brand_name':'Test'})
 for i in range(4): f.save_customer_profile('p'+str(i),p)
 for rev in range(1,4): f.save_customer_profile('p0',p,rev)
 assert len(f.customer_profiles(Page(offset=2,limit=2))['items'])==2
 assert [r['revision'] for r in f.customer_profile_history('p0',Page(offset=2,limit=2))['items']]==[2,1]


def test_download_log_redacts_ticket(caplog):
 async def app(scope,receive,send): await send({'type':'http.response.start','status':200})
 async def send(msg): pass
 asyncio.run(AuthDiagnostics(app)({'type':'http','method':'GET','path':'/download/secret-ticket','headers':[]},None,send))
 assert 'secret-ticket' not in caplog.text
 assert '/download/[redacted]' in caplog.text


def test_noncanonical_ticket_rejected(tmp_path):
 f=Factory(Registry([]),tmp_path);path=f.project('p')/'renders/a.mp4';path.parent.mkdir(parents=True);path.write_bytes(b'video')
 signer=DownloadSigner('https://example.com','test')
 ticket=signer.sign('p','renders/a.mp4').rsplit('/',1)[1]
 assert signer.verify(f,ticket)==path
 assert signer.verify(f,ticket+'=') is None
 raw=bytearray(base64.urlsafe_b64decode(ticket+'='*(-len(ticket)%4)));raw[-1]^=1
 assert signer.verify(f,base64.urlsafe_b64encode(raw).decode().rstrip('=')) is None


def test_bad_lottie_rejected():
 assert not validate_scene({'objects':[{'id':'a','recipe':'lottie','animation':{'layers':None,'fr':0,'ip':10,'op':-1,'w':-1,'h':'bad'}}]})['valid']


def test_browser_override_checked(monkeypatch):
 monkeypatch.setenv('PLAYWRIGHT_CHROME','/missing/browser')
 assert LemoRender().get_status()==ToolStatus.UNAVAILABLE


def test_failed_preview_invalidates_previous_manifest(tmp_path):
 import subprocess
 out=tmp_path/'preview';out.mkdir();(out/'latest.json').write_text('{"status":"completed"}')
 with patch('tools.graphics.motion_scene.subprocess.run',side_effect=subprocess.CalledProcessError(1,['node'],stderr='failure')):
  result=MotionScene().execute({'scene':{'objects':[{'id':'a','recipe':'sketch'}]},'output_path':str(out)})
 assert not result.success
 assert json.loads((out/'latest.json').read_text())=={'status':'failed','output_path':None}
