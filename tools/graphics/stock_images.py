"""Search free stock images, then download a selected candidate with provenance."""
from __future__ import annotations

import hashlib
import html
import io
import json
import os
import re
import time
import uuid
import warnings
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

from PIL import Image
from pydantic import Field

from content_factory.models import Model
from lib.paths import PROJECTS_DIR
from lib.research import fetch_bytes, now
from tools.base_tool import BaseTool, ResourceProfile, ToolResult, ToolRuntime

Provider = Literal['wikimedia', 'openverse', 'pexels', 'pixabay']
UA = 'OpenMontage/1.0 (+https://github.com/calesthio/OpenMontage)'
LICENSE_NOTE = ('Free download is not a blanket rights clearance. Check the original '
                'source, attribution/share-alike terms and any people, brands or property rights.')


class SearchInput(Model):
    project_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$')
    query: str = Field(min_length=2, max_length=100)
    provider: Provider = 'wikimedia'
    limit: int = Field(default=8, ge=1, le=20)
    page: int = Field(default=1, ge=1, le=100)
    orientation: Literal['any', 'landscape', 'portrait', 'square'] = 'any'
    min_width: int = Field(default=640, ge=0, le=10000)
    license_policy: Literal['commercial_editable', 'public_domain'] = 'commercial_editable'


class DownloadInput(Model):
    project_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$')
    search_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    candidate_id: str = Field(min_length=1, max_length=160)
    output_path: str | None = Field(default=None, description='Optional project-relative assets/ path ending in .jpg, .png or .webp; omit to use a format-correct stable filename.')
    scene_id: str = Field(default='unassigned', min_length=1, max_length=120)
    max_bytes: int = Field(default=20_000_000, ge=1024, le=30_000_000)


def clean(value, limit=800):
    return html.unescape(re.sub(r'<[^>]*>', '', str(value or '')))[:limit].strip()


def project(project_id):
    root = (PROJECTS_DIR / project_id).resolve()
    if root.parent != PROJECTS_DIR.resolve() or not (root / 'project.json').is_file():
        raise ValueError('Unknown project; create a factory project first')
    return root


def scoped(root, relative, area):
    p = (root / relative).resolve()
    if not p.is_relative_to(root / area) or p == root / area:
        raise ValueError(f'Path must remain inside project {area}/; escaping symlinks are rejected')
    return p


def api(url, params=None, headers=None):
    # Reuse the pinned-DNS public HTTPS client, including redirect and size bounds.
    _, _, raw = fetch_bytes(url + ('?' + urlencode(params) if params else ''),
                            headers={'User-Agent': UA, **(headers or {})}, limit=2_000_000)
    result = json.loads(raw)
    if result.get('error'):
        raise ValueError('Stock provider returned an API error; refine the query or try another provider')
    return result


def pixabay_response(project_id, params):
    # Pixabay requires API responses to be cached for 24 hours. The key is
    # hashed as part of the cache identity and is never written to disk.
    root = project(project_id)
    identity = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
    path = scoped(root, f'artifacts/stock-api-cache/{identity}.json', 'artifacts')
    if path.is_file() and path.stat().st_size <= 2_000_000:
        cached = json.loads(path.read_text(encoding='utf-8'))
        if cached['expires_at'] > time.time():
            return cached['response']
    response = api('https://pixabay.com/api/', params)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as f:
            json.dump({'expires_at':time.time()+86400, 'response':response}, f)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return response


def cc_license(code, version, url):
    code = clean(code).lower()
    if code not in {'cc0', 'pdm', 'by', 'by-sa'}:
        return None  # Never accept unknown, noncommercial or no-derivatives results.
    # The provider's explicit code is checked separately from its display label.
    if not str(url).startswith('https://creativecommons.org/'):
        return None
    label = {'cc0': 'CC0', 'pdm': 'Public Domain Mark', 'by': 'CC BY', 'by-sa': 'CC BY-SA'}[code]
    return {'code': code, 'name': (label + ' ' + clean(version, 20)).strip(),
            'url': url, 'attribution_required': code in {'by', 'by-sa'},
            'share_alike': code == 'by-sa'}


def commons_license(meta):
    val = lambda k: clean((meta.get(k) or {}).get('value'))
    label, url = val('LicenseShortName'), val('LicenseUrl')
    match = re.fullmatch(r'CC (BY-SA|BY) (\d\.\d)', label, re.I)
    if match:
        return cc_license(match[1].lower(), match[2], url)
    if label.lower() in {'cc0', 'cc0 1.0'}:
        return cc_license('cc0', '1.0', url or 'https://creativecommons.org/publicdomain/zero/1.0/')
    if label.lower() in {'public domain', 'public domain mark'}:
        return cc_license('pdm', '', url or 'https://creativecommons.org/publicdomain/mark/1.0/')
    return None


def candidate(provider, ident, title, landing, image, preview, width, height, creator, license):
    if not license or not image or not landing:
        return None
    creator = clean(creator, 300)
    if license['attribution_required'] and not creator:
        return None
    return {'id': provider + ':' + str(ident), 'provider': provider, 'source_id': str(ident),
            'title': clean(title), 'source_url': landing, 'download_url': image,
            'preview_url': preview, 'width': int(width or 0), 'height': int(height or 0),
            'creator': creator, 'license': license,
            'credit': f'{clean(title, 250)} — {creator or provider}. {license["name"]}. {landing} {license["url"]}'}


def search_provider(p):
    rows = []
    if p.provider == 'wikimedia':
        d = api('https://commons.wikimedia.org/w/api.php', {
            'action': 'query', 'format': 'json', 'generator': 'search',
            'gsrsearch': p.query + ' filetype:bitmap', 'gsrnamespace': 6,
            'gsrlimit': p.limit, 'gsroffset': (p.page - 1) * p.limit,
            'prop': 'imageinfo', 'iiprop': 'url|size|extmetadata', 'iiurlwidth': 1920})
        pages = sorted(d.get('query', {}).get('pages', {}).values(), key=lambda x: x.get('index', 0))
        for page in pages:
            info = (page.get('imageinfo') or [{}])[0]; meta = info.get('extmetadata') or {}
            rows.append(candidate(p.provider, page['pageid'], page.get('title'), info.get('descriptionurl'),
                info.get('thumburl') or info.get('url'), info.get('thumburl') or info.get('url'),
                info.get('thumbwidth') or info.get('width'), info.get('thumbheight') or info.get('height'),
                (meta.get('Artist') or {}).get('value'), commons_license(meta)))
    elif p.provider == 'openverse':
        params = {'q': p.query, 'page': p.page, 'page_size': p.limit, 'mature': 'false',
                  'license_type': 'commercial,modification'}
        if p.license_policy == 'public_domain': params['license'] = 'cc0,pdm'
        if p.orientation != 'any': params['aspect_ratio'] = {'landscape':'wide','portrait':'tall','square':'square'}[p.orientation]
        d = api('https://api.openverse.org/v1/images/', params)
        for item in d.get('results', []):
            rows.append(candidate(p.provider, item['id'], item.get('title'), item.get('foreign_landing_url'),
                item.get('url'), item.get('thumbnail'), item.get('width'), item.get('height'),
                item.get('creator'), cc_license(item.get('license'), item.get('license_version'), item.get('license_url'))))
    elif p.provider == 'pexels':
        key = os.environ.get('PEXELS_API_KEY', '').strip()
        if not key: raise ValueError('Pexels is not configured. Use wikimedia/openverse without a key, or ask the administrator to configure PEXELS_API_KEY.')
        params = {'query': p.query, 'page': p.page, 'per_page': p.limit}
        if p.orientation != 'any': params['orientation'] = p.orientation
        d = api('https://api.pexels.com/v1/search', params, {'Authorization': key})
        license = {'code':'pexels', 'name':'Pexels License', 'url':'https://www.pexels.com/license/',
                   'attribution_required':True, 'share_alike':False, 'note':'Preserve Pexels and photographer credits for API integration requirements.'}
        for item in d.get('photos', []):
            src = item.get('src') or {}
            rows.append(candidate(p.provider,item['id'],item.get('alt'),item.get('url'),
                src.get('original'),src.get('medium'),item.get('width'),item.get('height'),item.get('photographer'),license))
    else:
        key = os.environ.get('PIXABAY_API_KEY', '').strip()
        if not key: raise ValueError('Pixabay is not configured. Use wikimedia/openverse without a key, or ask the administrator to configure PIXABAY_API_KEY.')
        params = {'key':key,'q':p.query,'page':p.page,'per_page':max(3,p.limit),'safesearch':'true','image_type':'photo'}
        if p.orientation in {'landscape','portrait'}: params['orientation'] = {'landscape':'horizontal','portrait':'vertical'}[p.orientation]
        d = pixabay_response(p.project_id, params)
        license = {'code':'pixabay','name':'Pixabay Content License','url':'https://pixabay.com/service/license-summary/',
                   'attribution_required':False,'share_alike':False,'note':'Show Pixabay source in search results; source-specific restrictions still apply.'}
        for item in d.get('hits', [])[:p.limit]:
            # largeImageURL is the 1280px variant, not the 640px web preview.
            w, h = int(item.get('imageWidth') or 0), int(item.get('imageHeight') or 0)
            scale = min(1, 1280 / max(w, h)) if max(w, h) else 0
            rows.append(candidate(p.provider,item['id'],item.get('tags'),item.get('pageURL'),item.get('largeImageURL'),
                item.get('previewURL'),round(w*scale),round(h*scale),item.get('user'),license))
    result = []
    for row in rows:
        if not row: continue
        if p.license_policy == 'public_domain' and row['license']['code'] not in {'cc0','pdm'}: continue
        w,h = row['width'],row['height']
        if w < p.min_width or not h: continue
        if p.orientation == 'portrait' and not h > w: continue
        if p.orientation == 'landscape' and not w > h: continue
        if p.orientation == 'square' and not .9 <= w/h <= 1.1: continue
        result.append(row)
    return result[:p.limit]


class StockImageSearch(BaseTool):
    """Find free stock-image candidates with previews and licences; the calling AI selects the image."""
    name = 'stock_image_search'
    capability = 'stock_image'
    provider = 'free_stock'
    runtime = ToolRuntime.API
    input_schema = SearchInput.model_json_schema()
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=128, disk_mb=10, network_required=True)
    dependencies = ['python:PIL']
    agent_skills = ['free-stock-images']
    side_effects = ['writes a bounded candidate receipt under project artifacts']
    best_for = ['free stock photos', 'keyless Wikimedia Commons and Openverse search', 'Pexels and Pixabay with configured free API keys', 'source and licence selection before download']
    not_good_for = ['guaranteed rights clearance', 'AI image generation', 'offline search']
    install_instructions = 'Wikimedia and Openverse need no API key. Pexels/Pixabay require administrator-provisioned free API keys. Internet access and provider quotas apply.'
    def estimate_cost(self, inputs): return 0.0
    def execute(self, inputs):
        p = SearchInput.model_validate(inputs); root = project(p.project_id)
        rows = search_provider(p)
        search_id = uuid.uuid4().hex
        folder = scoped(root, 'artifacts/stock-searches', 'artifacts'); folder.mkdir(parents=True, exist_ok=True)
        receipt = {'version':1, 'search_id':search_id, 'created_at':now(), 'expires_at':time.time()+86400,
                   'query':p.query,'provider':p.provider,'page':p.page,'license_policy':p.license_policy,'candidates':rows}
        path = folder / (search_id+'.json')
        with path.open('x', encoding='utf-8') as f: json.dump(receipt,f,indent=2)
        return ToolResult(success=True,data={**receipt,'count':len(rows),'next_page':p.page+1 if rows else None,
            'pagination_note':'Filtering may return an empty/short page even when later provider pages contain candidates. Increment page explicitly to continue.',
            'available_sources':{'wikimedia':True,'openverse':True,'pexels':bool(os.getenv('PEXELS_API_KEY')),'pixabay':bool(os.getenv('PIXABAY_API_KEY'))},
            'note':LICENSE_NOTE,'selection_required':True},artifacts=[str(path)],cost_usd=0)


class StockImageDownload(BaseTool):
    """Download a chosen stock search candidate into project assets with credits and an asset-manifest entry."""
    name = 'stock_image_download'
    capability = 'stock_image'
    provider = 'free_stock'
    runtime = ToolRuntime.API
    input_schema = DownloadInput.model_json_schema()
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, disk_mb=60, network_required=True)
    dependencies = ['python:PIL']
    agent_skills = ['free-stock-images']
    best_for = ['materializing selected stock images for Remotion or HyperFrames', 'saved attribution and provenance', 'free photo assets']
    not_good_for = ['arbitrary URL downloads', 'SVG or animated images', 'automatic creative selection']
    side_effects = ['writes selected image and provenance/credit sidecars under project assets']
    install_instructions = 'Downloads selected receipts from stock_image_search; internet access and Pillow are required. No additional credentials are needed for downloading.'
    def estimate_cost(self, inputs): return 0.0
    def execute(self, inputs):
        p = DownloadInput.model_validate(inputs); root = project(p.project_id)
        catalog = scoped(root,'artifacts/stock-searches/'+p.search_id+'.json','artifacts')
        if not catalog.is_file() or catalog.stat().st_size > 2_000_000: raise ValueError('Unknown or oversized search receipt; run stock_image_search first')
        receipt = json.loads(catalog.read_text(encoding='utf-8'))
        if receipt['expires_at'] < time.time(): raise ValueError('Search expired; repeat it to refresh source URLs and licences')
        row = next((r for r in receipt['candidates'] if r['id']==p.candidate_id),None)
        if row is None: raise ValueError('candidate_id must identify a result in this project search receipt')
        # Receipts are project data, not authority for bypassing the license filter.
        code = row['license']['code']
        if code not in {'cc0','pdm','by','by-sa','pexels','pixabay'}: raise ValueError('Unsupported stock licence')
        final, ctype, data = fetch_bytes(row['download_url'], headers={'User-Agent':UA}, limit=p.max_bytes)
        if not ctype.lower().startswith('image/'): raise ValueError('Provider did not return image bytes; select another candidate')
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                fmt=image.format; width,height=image.size
                if width*height>40_000_000: raise ValueError('Stock image exceeds 40 megapixels; select a smaller candidate')
                if fmt not in {'JPEG','PNG','WEBP'} or getattr(image,'n_frames',1)!=1: raise ValueError('Use a static JPEG, PNG or WebP stock image')
                image.verify()
        suffix={'JPEG':'.jpg','PNG':'.png','WEBP':'.webp'}[fmt]
        stable=hashlib.sha256(p.candidate_id.encode()).hexdigest()[:16]
        out=scoped(root,p.output_path or f'assets/images/{row["provider"]}-{stable}{suffix}','assets')
        if out.suffix.lower() not in ({'.jpg','.jpeg'} if fmt=='JPEG' else {suffix}): raise ValueError('output_path extension must match image format; omit it for automatic naming')
        provenance=out.with_suffix(out.suffix+'.source.json');credit=out.with_suffix(out.suffix+'.credit.txt')
        digest=hashlib.sha256(data).hexdigest()
        record={**row,'search_id':p.search_id,'query':receipt['query'],'retrieved_at':now(),
                'final_download_url':final,'sha256':digest,'width':width,'height':height,'bytes':len(data),'note':LICENSE_NOTE}
        paths=[out,provenance,credit]
        if any(x.is_symlink() for x in paths): raise ValueError('Output files cannot be symlinks')
        if any(x.exists() for x in paths):
            if not all(x.is_file() for x in paths): raise ValueError('Output already exists; choose a new output_path')
            old=json.loads(provenance.read_text(encoding='utf-8'))
            if old.get('id')!=p.candidate_id or old.get('sha256')!=digest or hashlib.sha256(out.read_bytes()).hexdigest()!=digest:
                raise ValueError('Output already exists with different content; choose a new output_path')
        else:
            out.parent.mkdir(parents=True,exist_ok=True);created=[]
            try:
                for path,body in [(out,data),(provenance,json.dumps(record,indent=2).encode()),(credit,(row['credit']+'\n'+LICENSE_NOTE+'\n').encode())]:
                    with path.open('xb') as f: created.append(path); f.write(body)
            except Exception:
                for path in created: path.unlink(missing_ok=True)
                raise
        entry={'id':'stock-'+stable,'type':'image','path':str(out.relative_to(root)),
               'source_tool':self.name,'scene_id':p.scene_id,'provider':row['provider'],'subtype':'stock',
               'license':row['license']['name']+' '+row['license']['url'],'original_url':row['source_url'],
               'cost_usd':0,'resolution':f'{width}x{height}','format':suffix[1:],
               'generation_summary':'Downloaded selected free stock image. '+row['credit']}
        return ToolResult(success=True,data={'output_path':str(out),'sha256':digest,'provenance_path':str(provenance),
            'credit_path':str(credit),'credit':row['credit'],'license':row['license'],'asset_manifest_entry':entry,
            'visual_review_required':True,'note':LICENSE_NOTE},artifacts=[str(x) for x in paths],cost_usd=0)
