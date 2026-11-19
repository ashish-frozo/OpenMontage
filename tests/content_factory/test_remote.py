import asyncio
import json

import pytest
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.auth import AccessToken
from starlette.testclient import TestClient

from content_factory.remote import OwnerGitHubProvider, DownloadSigner, build_remote, load_config
from content_factory.service import Factory


def config():
    return dict(client_id="test-client", client_secret="test-secret-not-real",
                base_url="https://factory.example.com", allowed_user_ids=["214779977"])


def test_config_requires_private_permissions_and_https(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config()))
    path.chmod(0o644)
    with pytest.raises(ValueError, match="600"):
        load_config(path)
    path.chmod(0o600)
    assert load_config(path)["allowed_user_ids"] == ["214779977"]
    path.write_text(json.dumps({**config(), "base_url": "http://factory.example.com"}))
    with pytest.raises(ValueError, match="HTTPS"):
        load_config(path)


def test_only_owner_can_use_verified_tokens(monkeypatch):
    current = {"sub": "214779977"}

    async def verified(self, token):
        return AccessToken(token=token, client_id="test", scopes=["read:user"], claims=current.copy())

    monkeypatch.setattr(GitHubProvider, "load_access_token", verified)
    provider = OwnerGitHubProvider(**config(), required_scopes=["read:user"])
    assert asyncio.run(provider.load_access_token("fake")) is not None
    current["sub"] = "999"
    assert asyncio.run(provider.load_access_token("fake")) is None
    current.clear()
    assert asyncio.run(provider.load_access_token("fake")) is None


def test_http_rejects_anonymous_and_advertises_oauth():
    app = build_remote(config()).http_app(path="/mcp")
    with TestClient(app, base_url="https://factory.example.com") as client:
        response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert response.status_code == 401
        assert "resource_metadata=" in response.headers["www-authenticate"]
        metadata = client.get("/.well-known/oauth-authorization-server").json()
        assert metadata["issuer"] == "https://factory.example.com/"
        assert "S256" in metadata["code_challenge_methods_supported"]


def test_scoped_media_download(tmp_path, monkeypatch):
    factory = Factory(projects_dir=tmp_path)
    renders = factory.project("test") / "renders"
    renders.mkdir(parents=True)
    (renders / "film.mp4").write_bytes(b"film")
    signer = DownloadSigner(config()["base_url"], config()["client_secret"])
    with TestClient(build_remote(config(), factory).http_app(path="/mcp"), base_url=config()["base_url"]) as client:
        url = signer.sign("test", "renders/film.mp4")
        result = client.get(url)
        assert result.status_code == 200 and result.content == b"film"
        assert "inline" in result.headers["content-disposition"]
        assert result.headers["content-type"] == "video/mp4"
        partial = client.get(url, headers={"Range": "bytes=0-1"})
        assert partial.status_code == 206 and partial.content == b"fi"
        assert client.get(url[:-1] + ("X" if url[-1] != "X" else "Y")).status_code == 404
        assert client.get("/download/garbage").status_code == 404
        with pytest.raises(ValueError):
            signer.media_path(factory, "test", "../../other.mp4")
        monkeypatch.setattr("content_factory.remote.time.time", lambda: 10**11)
        assert client.get(url).status_code == 404
