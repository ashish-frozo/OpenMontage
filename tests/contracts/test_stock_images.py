import io
import json
from pathlib import Path

import pytest
import yaml
from PIL import Image, UnidentifiedImageError

from schemas.artifacts import validate_artifact
from tools.graphics import stock_images as stock


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(stock, 'PROJECTS_DIR', tmp_path)
    root = tmp_path / 'demo'
    root.mkdir()
    (root / 'project.json').write_text('{}', encoding='utf-8')
    return root


def item(ident='one', license='by', width=1200, height=800):
    return {'id': ident, 'title': 'Forest', 'foreign_landing_url': 'https://source.example/photo/'+ident,
            'url': 'https://images.example/'+ident+'.png', 'thumbnail': 'https://images.example/preview.png',
            'width': width, 'height': height, 'creator': '<b>Alice</b>',
            'license': license, 'license_version': '4.0',
            'license_url': 'https://creativecommons.org/licenses/'+license+'/4.0/'}


def search(monkeypatch, items=None, **kwargs):
    monkeypatch.setattr(stock, 'api', lambda *a, **kw: {'results': items if items is not None else [item(), item('two')]})
    return stock.StockImageSearch().execute({'project_id':'demo','query':'forest','provider':'openverse', **kwargs})


def image_bytes():
    output = io.BytesIO()
    Image.new('RGB', (800,600), 'green').save(output, format='PNG')
    return output.getvalue()


def download(monkeypatch, result, **kwargs):
    monkeypatch.setattr(stock, 'fetch_bytes', lambda *a, **kw: ('https://images.example/two.png', 'image/png', image_bytes()))
    return stock.StockImageDownload().execute({'project_id':'demo','search_id':result.data['search_id'],
                                              'candidate_id':'openverse:two','scene_id':'shot-2', **kwargs})


def test_search_requires_selection_and_filters_licences(project, monkeypatch):
    result = search(monkeypatch, [item('by'), item('cc0','cc0'), item('nc','by-nc'), item('nd','by-nd'), item('unknown','unknown')])
    assert [r['source_id'] for r in result.data['candidates']] == ['by','cc0']
    assert result.data['selection_required']
    assert result.data['candidates'][0]['creator'] == 'Alice'
    assert not list((project / 'assets').glob('**/*'))
    assert Path(result.artifacts[0]).is_file()
    result = search(monkeypatch, [item('by'),item('cc0','cc0')], license_policy='public_domain')
    assert [r['source_id'] for r in result.data['candidates']] == ['cc0']


def test_search_orientation_and_resolution(project, monkeypatch):
    result = search(monkeypatch, [item('wide'),item('portrait',width=800,height=1200),item('small',width=300,height=500)],orientation='portrait')
    assert [r['source_id'] for r in result.data['candidates']] == ['portrait']


def test_download_selected_candidate_with_valid_manifest_and_sidecars(project, monkeypatch):
    result = search(monkeypatch)
    output = download(monkeypatch, result)
    assert output.success and output.cost_usd == 0
    assert len(output.artifacts) == 3
    assert Path(output.data['output_path']).read_bytes() == image_bytes()
    record = json.loads(Path(output.data['provenance_path']).read_text())
    assert record['source_id'] == 'two'
    assert record['sha256'] == output.data['sha256']
    assert record['width'] == 800
    assert 'Alice' in Path(output.data['credit_path']).read_text()
    validate_artifact('asset_manifest', {'version':'1.0','assets':[output.data['asset_manifest_entry']]})
    assert download(monkeypatch, result).success  # Same selection never overwrites other content.
    Path(output.data['output_path']).write_bytes(b'user modification')
    with pytest.raises(ValueError, match='different content'):
        download(monkeypatch, result)


@pytest.mark.parametrize('path', ['../escape.png','/tmp/escape.png','artifacts/escape.png','assets/wrong.jpg'])
def test_reject_invalid_output_path(project, monkeypatch, path):
    result = search(monkeypatch)
    with pytest.raises(ValueError, match='Path must|extension'):
        download(monkeypatch, result, output_path=path)


def test_reject_symlink_escape(project, monkeypatch, tmp_path):
    result = search(monkeypatch)
    (project / 'assets').symlink_to(tmp_path / 'elsewhere', target_is_directory=True)
    with pytest.raises(ValueError, match='Path must'):
        download(monkeypatch, result)


def test_reject_wrong_candidate_expired_receipt_and_non_image(project, monkeypatch):
    result = search(monkeypatch)
    inputs = {'project_id':'demo','search_id':result.data['search_id'],'candidate_id':'openverse:missing'}
    with pytest.raises(ValueError, match='candidate_id'):
        stock.StockImageDownload().execute(inputs)
    inputs['candidate_id'] = 'openverse:two'
    monkeypatch.setattr(stock, 'fetch_bytes', lambda *a, **kw: ('https://example.com','text/html',b'<html>bad</html>'))
    with pytest.raises(ValueError, match='image bytes'):
        stock.StockImageDownload().execute(inputs)
    path = Path(result.artifacts[0])
    receipt=json.loads(path.read_text()); receipt['expires_at']=0
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='expired'):
        stock.StockImageDownload().execute(inputs)


def test_download_passes_network_bound_and_rejects_svg(project, monkeypatch):
    result=search(monkeypatch)
    def fake_fetch(url, **kwargs):
        assert kwargs['limit']==12345
        return url,'image/svg+xml',b'<svg></svg>'
    monkeypatch.setattr(stock,'fetch_bytes',fake_fetch)
    with pytest.raises(UnidentifiedImageError):
        stock.StockImageDownload().execute({'project_id':'demo','search_id':result.data['search_id'],
                                           'candidate_id':'openverse:two','max_bytes':12345})


@pytest.mark.parametrize('provider,env', [('pexels','PEXELS_API_KEY'),('pixabay','PIXABAY_API_KEY')])
def test_missing_optional_credentials_give_keyless_options(project, monkeypatch, provider, env):
    monkeypatch.delenv(env, raising=False)
    with pytest.raises(ValueError, match='wikimedia/openverse'):
        stock.StockImageSearch().execute({'project_id':'demo','query':'forest','provider':provider})


def test_commons_license_and_html_normalization(project, monkeypatch):
    monkeypatch.setattr(stock,'api',lambda *a,**k: {'query':{'pages':{'1':{'pageid':1,'title':'Beech forest',
        'imageinfo':[{'url':'https://images.example/a.jpg','descriptionurl':'https://commons.wikimedia.org/wiki/File:A',
        'width':1200,'height':800,'extmetadata':{'Artist':{'value':'<a href="/">Alice &amp; Bob</a>'},
        'LicenseShortName':{'value':'CC BY-SA 4.0'},'LicenseUrl':{'value':'https://creativecommons.org/licenses/by-sa/4.0/'}}}]}}}})
    r=stock.StockImageSearch().execute({'project_id':'demo','query':'forest'})
    assert r.data['candidates'][0]['creator']=='Alice & Bob'
    assert r.data['candidates'][0]['license']['share_alike']


def test_pixabay_download_variant_dimensions(project, monkeypatch):
    monkeypatch.setenv('PIXABAY_API_KEY','test-key')
    monkeypatch.setattr(stock,'api',lambda *a,**k: {'hits':[{'id':1,'tags':'forest','pageURL':'https://pixabay.com/photos/1',
        'largeImageURL':'https://images.example/a.jpg','imageWidth':2000,'imageHeight':3000,'user':'Alice'}]})
    result=stock.StockImageSearch().execute({'project_id':'demo','query':'forest','provider':'pixabay','orientation':'portrait'})
    assert result.data['count']==1
    assert result.data['candidates'][0]['width']==853
    assert 'test-key' not in Path(result.artifacts[0]).read_text()


def test_pixabay_caches_api_responses_without_credentials(project, monkeypatch):
    monkeypatch.setenv('PIXABAY_API_KEY','secret-test-key')
    calls=[]
    def fake_api(*a, **k):
        calls.append(1)
        return {'hits':[]}
    monkeypatch.setattr(stock,'api',fake_api)
    for _ in range(2):
        stock.StockImageSearch().execute({'project_id':'demo','query':'forest','provider':'pixabay'})
    assert len(calls)==1
    cache=list((project/'artifacts/stock-api-cache').glob('*.json'))
    assert len(cache)==1 and 'secret-test-key' not in cache[0].read_text()


@pytest.mark.live_api
@pytest.mark.parametrize('provider',['wikimedia','openverse'])
def test_live_free_search_and_download(project, provider):
    result=stock.StockImageSearch().execute({'project_id':'demo','query':'forest','provider':provider,'limit':2})
    assert result.data['count']>0
    output=stock.StockImageDownload().execute({'project_id':'demo','search_id':result.data['search_id'],
        'candidate_id':result.data['candidates'][0]['id']})
    assert output.success and Path(output.data['output_path']).stat().st_size>0


def test_registry_discovers_operations_and_asset_pipeline_permissions():
    from tools.tool_registry import ToolRegistry
    registry=ToolRegistry(); registry.discover()
    assert {'stock_image_search','stock_image_download'} <= registry._tools.keys()
    root=Path(__file__).resolve().parents[2]
    for path in (root/'pipeline_defs').glob('*.yaml'):
        if path.stem in {'framework-smoke','openshorts-clipping'}: continue
        for stage in yaml.safe_load(path.read_text())['stages']:
            if stage['name']=='assets':
                assert {'stock_image_search','stock_image_download'} <= set(stage['tools_available']),path
