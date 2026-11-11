import json
import os
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from voc.config import Settings, load_settings
from voc.main import create_app
from voc.provider import ProviderError, QwenClient


HEADERS = {"X-VOC-Settings": "1"}
BODY = {"base_url": "https://provider.example/v1", "model": "example-model", "region": "test"}
SECRET = "unit-test-secret-not-a-real-key"


@pytest.fixture
def local(tmp_path):
    settings = Settings(tmp_path, SECRET, BODY["base_url"], "test")
    app = create_app(settings, run_worker=False)
    with TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000)) as client:
        yield client, settings, app.state.worker


def test_no_secret_returned_and_atomic_persistence(local, monkeypatch):
    client, settings, worker = local
    original = client.get("/api/settings/model")
    assert original.status_code == 200 and SECRET not in original.text
    saved = client.put("/api/settings/model", json=BODY, headers=HEADERS)
    assert saved.status_code == 200 and SECRET not in saved.text
    assert saved.json()["configured"] and saved.json()["saved_locally"]
    assert json.loads(settings.model_config_path.read_text())["api_key"] == SECRET
    assert not list(settings.root.glob(".model-config-*"))
    monkeypatch.setenv("VOC_DATA_DIR", str(settings.root))
    monkeypatch.setenv("QWEN_API_KEY", "other-env-secret")
    loaded = load_settings()
    assert loaded.api_key == SECRET and loaded.model == BODY["model"]
    assert worker.provider.settings is settings
    assert client.get("/api/health").json()["model"] == BODY["model"]


def test_clear_and_replace_secret(local):
    client, settings, _ = local
    response = client.put("/api/settings/model", json={**BODY, "api_key": "replacement-test-key"}, headers=HEADERS)
    assert response.status_code == 200 and "replacement-test-key" not in response.text
    assert settings.api_key == "replacement-test-key"
    response = client.put("/api/settings/model", json={**BODY, "clear_api_key": True}, headers=HEADERS)
    assert response.status_code == 200 and not response.json()["configured"]
    assert settings.api_key == ""


@pytest.mark.parametrize("url", ["https://another.example/v1", "https://provider.example/new-v1"])
def test_endpoint_change_requires_new_secret(local, url):
    client, settings, _ = local
    for route, method in [("", "PUT"), ("/test", "POST")]:
        response = client.request(method, "/api/settings/model" + route, json={**BODY, "base_url": url}, headers=HEADERS)
        assert response.status_code == 422 and SECRET not in response.text
    assert settings.base_url == BODY["base_url"]
    response = client.put("/api/settings/model", json={**BODY, "base_url": url, "api_key": "new-provider-test-key"}, headers=HEADERS)
    assert response.status_code == 200


@pytest.mark.parametrize("url", ["http://provider.example/v1", "file:///etc/passwd", "https://user:password@provider.example/v1", "https://provider.example/v1?key=private", "https://provider.example/v1#private", "https://provider.example/v1/chat/completions", "https://provider.example:bad/v1"])
def test_invalid_endpoints(local, url):
    client, _, _ = local
    response = client.put("/api/settings/model", json={**BODY, "base_url": url, "api_key": SECRET}, headers=HEADERS)
    assert response.status_code == 422
    assert SECRET not in response.text and "password@" not in response.text


def test_local_http_endpoint_allowed(local):
    client, _, _ = local
    response = client.put("/api/settings/model", json={**BODY, "base_url": "http://127.0.0.1:8080/v1", "api_key": "local-test-key"}, headers=HEADERS)
    assert response.status_code == 200


def test_cross_origin_and_rebinding_blocked(local):
    client, _, _ = local
    assert client.get("/api/settings/model", headers={"Host": "evil.example"}).status_code == 403
    for origin in ["https://evil.example", "null", "http://localhost:5173"]:
        assert client.get("/api/settings/model", headers={"Origin": origin}).status_code == 403
        assert client.put("/api/settings/model", json=BODY, headers={**HEADERS, "Origin": origin}).status_code == 403
    assert client.put("/api/settings/model", json=BODY).status_code == 403
    assert client.put("/api/settings/model", json=BODY, headers={**HEADERS, "Origin": "http://127.0.0.1:8765"}).status_code == 200


def test_nonlocal_client_rejected(tmp_path):
    app = create_app(Settings(tmp_path, SECRET, BODY["base_url"], "test"), run_worker=False)
    with TestClient(app, base_url="http://127.0.0.1", client=("192.0.2.10", 12345)) as client:
        assert client.get("/api/settings/model").status_code == 403
        assert client.put("/api/settings/model", json=BODY, headers=HEADERS).status_code == 403


def test_busy_worker_rejects_save_and_test(local):
    client, settings, worker = local
    with worker.configuration_lock:
        assert client.put("/api/settings/model", json=BODY, headers=HEADERS).status_code == 409
        assert client.post("/api/settings/model/test", json=BODY, headers=HEADERS).status_code == 409
    assert not settings.model_config_path.exists()


def test_connection_probe_does_not_persist_or_echo_remote_content(local, monkeypatch):
    client, settings, _ = local
    def complete(instance, prompt, **kwargs):
        assert prompt == "Reply with OK only." and kwargs["attempts"] == 1
        assert instance.settings.api_key == SECRET
        return "remote-response", {"response_model": SECRET}
    monkeypatch.setattr(QwenClient, "complete", complete)
    response = client.post("/api/settings/model/test", json=BODY, headers=HEADERS)
    assert response.status_code == 200 and response.json()["scope"] == "text-only"
    assert SECRET not in response.text and not settings.model_config_path.exists()


def test_persistence_failure_leaves_live_config_untouched(local, monkeypatch):
    client, settings, _ = local
    def fail(*args):
        raise OSError("unit-test write error")
    monkeypatch.setattr(os, "replace", fail)
    response = client.put("/api/settings/model", json=BODY, headers=HEADERS)
    assert response.status_code == 500 and settings.model != BODY["model"]
    assert not list(settings.root.glob(".model-config-*"))


def test_validation_errors_never_echo_request_secret(local):
    client, _, _ = local
    for body in [{**BODY, "api_key": SECRET + "\n"}, {**BODY, "api_key": {"secret": SECRET}}, {**BODY, "api_key": SECRET, "extra": SECRET}]:
        response = client.put("/api/settings/model", json=body, headers=HEADERS)
        assert response.status_code == 422 and SECRET not in response.text


def test_environment_configuration_does_not_read_personal_store(tmp_path, monkeypatch):
    monkeypatch.setenv("VOC_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("VOC_CREDENTIALS_FILE", raising=False)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("QWEN_MODEL", "configured-model")
    settings = load_settings()
    assert settings.api_key == "" and settings.model == "configured-model"


def test_provider_never_returns_upstream_error_body(local, monkeypatch):
    _, settings, _ = local
    transport = httpx.MockTransport(lambda request: httpx.Response(401, text=SECRET + " private upstream details"))
    real_client = httpx.Client
    monkeypatch.setattr("voc.provider.httpx.Client", lambda **kwargs: real_client(transport=transport, **kwargs))
    with pytest.raises(ProviderError) as error:
        QwenClient(settings).complete("test", attempts=1)
    assert "401" in str(error.value) and SECRET not in str(error.value) and "upstream" not in str(error.value)


def test_provider_does_not_follow_redirects(local, monkeypatch):
    _, settings, _ = local
    requests = []
    def redirect(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://another.example/v1"})
    real_client = httpx.Client
    monkeypatch.setattr("voc.provider.httpx.Client", lambda **kwargs: real_client(transport=httpx.MockTransport(redirect), **kwargs))
    with pytest.raises(ProviderError):
        QwenClient(settings).complete("test", attempts=1)
    assert len(requests) == 1
