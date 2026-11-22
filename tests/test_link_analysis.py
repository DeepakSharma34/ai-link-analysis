import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import analysis_service, llm_service, website_extractor

client = TestClient(app)

FAKE = {
    "brand": {"name": "Acme Web", "category": "Web Development", "summary": "Builds websites."},
    "analysis": {
        "competitor_analysis": {"brand_overview": "x", "competitors": [
            {"name": "Acme Web"}, {"name": "Rival One"}, {"name": "Rival Two"}, {"name": "Rival Three"}]},
        "target_search_queries": [{"query": f"q{i}", "platforms": ["Twitter", "Google"]} for i in range(5)],
        "seo_improvements": {"primary_keyword": "web development"},
        "top_services": [{"name": "Websites"}],
        "target_audience": {"primary_audience": ["Small businesses"]},
    },
}


@pytest.fixture(autouse=True)
def stub(monkeypatch):
    analysis_service._CACHE.clear()

    async def fake_extract(url):
        return url, "x" * 500, [url]

    async def fake_generate(system, user, provider, model, max_tokens=4000):
        return llm_service.LLMReply(json.dumps(FAKE), provider, model, 5, 100, 50)

    monkeypatch.setattr(website_extractor, "extract_website", fake_extract)
    monkeypatch.setattr(llm_service, "generate", fake_generate)
    monkeypatch.setattr("app.utils.validators.socket.getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])


def test_success_and_schema():
    r = client.post("/link-analysis", json={"url": "https://example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] and len(body["analysis"]["target_search_queries"]) == 5
    assert body["analysis"]["target_search_queries"][0]["platforms"] == ["X", "Google"]
    names = [c["name"] for c in body["analysis"]["competitor_analysis"]["competitors"]]
    assert "Acme Web" not in names  # own brand removed


def test_cache_hit():
    client.post("/link-analysis", json={"url": "https://example.com"})
    assert client.post("/link-analysis", json={"url": "https://example.com"}).json()["meta"]["cached"] is True


@pytest.mark.parametrize("url", ["ftp://example.com", "javascript:alert(1)", "https://user:pw@example.com", "notaurl"])
def test_invalid_urls(url):
    assert client.post("/link-analysis", json={"url": url}).status_code == 400


@pytest.mark.parametrize("url", ["http://127.0.0.1", "http://169.254.169.254/latest/meta-data", "http://10.0.0.5",
                                 "http://[::1]", "http://[::ffff:127.0.0.1]", "https://example.com:6379"])
def test_ssrf_blocked(url):
    r = client.post("/link-analysis", json={"url": url})
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsafe_url"


def test_missing_body():
    assert client.post("/link-analysis", json={}).status_code == 422
