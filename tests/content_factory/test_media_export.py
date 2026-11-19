import base64
import pytest
from content_factory.media import export_media
from content_factory.service import Factory
from content_factory.registry import Registry
from content_factory.models import ProjectConfig

def test_binary_chunks_and_change_guard(tmp_path):
    f=Factory(Registry([]),tmp_path);f.create('media','Media','animation',ProjectConfig())
    p=f.project('media')/'assets/test.wav';p.write_bytes(bytes(range(256))*1100)
    a=export_media(f,'media','assets/test.wav',mode='bytes')
    b=export_media(f,'media','assets/test.wav',mode='bytes',offset=a['next_offset'],expected_sha256=a['sha256'])
    assert base64.b64decode(a['data'])+base64.b64decode(b['data'])==p.read_bytes()
    assert b['next_offset'] is None
    p.write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed'): export_media(f,'media','assets/test.wav',mode='bytes',expected_sha256=a['sha256'])
    with pytest.raises(ValueError): export_media(f,'media','../secret.wav')
    outside=tmp_path/'outside.wav';outside.write_bytes(b'x');p.unlink();p.symlink_to(outside)
    with pytest.raises(ValueError): export_media(f,'media','assets/test.wav')
