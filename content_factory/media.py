"""Bounded media exports shared by local and remote MCP clients."""
import base64
import hashlib
import mimetypes
from pathlib import Path

EXTENSIONS={'.mp4','.mov','.webm','.mkv','.wav','.mp3','.m4a','.aac','.ogg','.flac','.png','.jpg','.jpeg','.webp','.gif','.srt','.vtt'}

def validate_relative_media_path(relative_path):
    relative=Path(relative_path)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts or relative.parts[0] not in {'renders','assets'}:
        raise ValueError('Choose a relative media path under renders/ or assets/')
    if relative.suffix.lower() not in EXTENSIONS:
        raise ValueError('Unsupported media file type')
    return relative.as_posix()

def media_path(factory,project_id,relative_path):
    root=factory.project(project_id).resolve();relative=Path(validate_relative_media_path(relative_path))
    path=(root/relative).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() not in EXTENSIONS or not path.is_file():
        raise ValueError('Media file is unavailable')
    return path


def export_media(factory,project_id,relative_path,signer=None,mode='link',offset=0,max_bytes=196608,expected_sha256=None):
    path=media_path(factory,project_id,relative_path)
    if mode not in {'link','bytes'}: raise ValueError('mode must be link or bytes')
    if not 0<=offset or not 1<=max_bytes<=262144: raise ValueError('offset must be nonnegative; max_bytes must be 1..262144')
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        before=path.stat()
        for chunk in iter(lambda:stream.read(1024*1024),b''): digest.update(chunk)
        sha=digest.hexdigest()
        if expected_sha256 and expected_sha256!=sha: raise ValueError('Media changed; restart export from offset zero')
        if offset>before.st_size: raise ValueError('offset exceeds file size')
        if mode=='bytes':
            stream.seek(offset);chunk=stream.read(max_bytes)
        after=path.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns): raise ValueError('Media changed during export; retry')
    result={'project_id':project_id,'relative_path':relative_path,'filename':path.name,'mime_type':mimetypes.guess_type(path.name)[0] or 'application/octet-stream','bytes':before.st_size,'sha256':sha}
    if signer:
        result.update(download_url=signer.sign(project_id,relative_path),expires_in_seconds=300)
    if mode=='bytes':
        end=offset+len(chunk)
        result.update(encoding='base64',data=base64.b64encode(chunk).decode(),offset=offset,returned_bytes=len(chunk),next_offset=end if end<before.st_size else None)
    elif not signer:
        result.update(download_available=False,next_action='Call factory_export_media with mode=bytes; concatenate decoded chunks using next_offset and expected_sha256.')
    return result
