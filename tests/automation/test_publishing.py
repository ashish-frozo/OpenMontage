import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
import pytest
from content_factory.service import Factory
from content_factory.registry import Registry
from content_factory.models import ProjectConfig
from content_factory import publishing as p

@pytest.fixture
def delivery(tmp_path,monkeypatch):
 f=Factory(Registry([]),tmp_path);f.create('film','Film','animation',ProjectConfig())
 video=f.project('film')/'renders/final.mp4';video.write_bytes(b'video')
 data=p.Delivery(platform='youtube',account='test-account',video_path=str(video),quality_id='q1',title='Test',due_at=datetime.now(timezone.utc)-timedelta(seconds=1)).model_dump(mode='json')
 data.update(config_revision=1,video_sha256='hash')
 with f.db('film') as db:
  p.db_init(db);db.execute("INSERT INTO deliveries VALUES ('d','unique',?,'prepared',NULL,NULL,NULL)",(json.dumps(data),))
 monkeypatch.setattr(p,'check',lambda *args:video)
 monkeypatch.setattr(p.shutil,'which',lambda name:'/bin/example')
 return f

def test_uncertain_upload_is_never_retried(delivery,monkeypatch):
 calls=[]
 def unknown(*args,**kwargs):calls.append(args);raise TimeoutError('unknown outcome')
 monkeypatch.setattr(p,'cli',unknown)
 assert p.publish(delivery,'film','d')['status']=='uncertain'
 assert p.publish(delivery,'film','d')['status']=='uncertain'
 assert len(calls)==1

def test_successful_upload_is_idempotent(delivery,monkeypatch):
 calls=[]
 def upload(*args,**kwargs):calls.append(args);return {'data':{'id':'video1'}}
 monkeypatch.setattr(p,'cli',upload)
 assert p.publish(delivery,'film','d')['remote_id']=='video1'
 assert p.publish(delivery,'film','d')['status']=='uploaded'
 assert len(calls)==1

def test_instagram_container_survives_reconnect(delivery,monkeypatch):
 with delivery.db('film') as db:
  data=json.loads(db.execute('SELECT data FROM deliveries').fetchone()[0]);data.update(platform='instagram',privacy='public')
  db.execute('UPDATE deliveries SET data=?',(json.dumps(data),))
 calls=[]
 def execute(slug,*args,**kwargs):
  calls.append(slug)
  return {'data':{'status_code':'FINISHED'}} if slug=='INSTAGRAM_GET_POST_STATUS' else {'data':{'id':'container1' if slug=='INSTAGRAM_POST_IG_USER_MEDIA' else 'media1'}}
 monkeypatch.setattr(p,'cli',execute)
 class Signer:
  def sign(self,*args,**kwargs):return 'https://example.com/media'
 assert p.publish(delivery,'film','d',Signer())['status']=='container_ready'
 assert p.publish(delivery,'film','d',Signer())['status']=='published'
 p.publish(delivery,'film','d',Signer())
 assert calls==['INSTAGRAM_POST_IG_USER_MEDIA','INSTAGRAM_GET_POST_STATUS','INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH']

def test_schedule_and_configuration_guard(delivery,monkeypatch):
 with delivery.db('film') as db:
  data=json.loads(db.execute('SELECT data FROM deliveries').fetchone()[0]);data['due_at']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
  db.execute('UPDATE deliveries SET data=?',(json.dumps(data),))
 assert p.publish(delivery,'film','d')['status']=='scheduled'


def test_no_policy_cannot_publish(delivery):
 data=json.loads(p.status(delivery,'film','d')['data'])
 request=p.Delivery.model_validate({k:v for k,v in data.items() if k not in {'config_revision','video_sha256'}})
 # Restore actual guard because fixture replaces it for lifecycle isolation.
 from importlib import reload
 module=reload(p)
 with pytest.raises(ValueError,match='policy'):module.check(delivery,'film',request)

def test_expired_instagram_container_stops_polling(delivery,monkeypatch):
 with delivery.db('film') as db:
  data=json.loads(db.execute('SELECT data FROM deliveries').fetchone()[0]);data.update(platform='instagram',privacy='public')
  db.execute("UPDATE deliveries SET data=?,status='container_ready',container_id='c'",(json.dumps(data),))
 monkeypatch.setattr(p,'cli',lambda *a,**k:{'data':{'status_code':'EXPIRED'}})
 assert p.publish(delivery,'film','d',object())['status']=='blocked'
