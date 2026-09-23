"""Local-origin enforcement, validation, and ranged downloads."""

import importlib
import time

from fastapi.testclient import TestClient
from PIL import Image

from server import config


def test_api_security_and_ranged_file(tmp_path, monkeypatch):
    game = tmp_path / "game"
    remix = game / "rtx-remix"
    remix.mkdir(parents=True)
    (game / "hl2").mkdir()
    Image.new("RGB", (32, 32), "green").save(remix / "sample.png")
    monkeypatch.setattr(config, "GAME", game)
    monkeypatch.setattr(config, "REMIX", remix)
    monkeypatch.setattr(config, "DATA", tmp_path / "data")
    module = importlib.import_module("server.app")
    module.catalog.scan()
    client = TestClient(module.app, base_url=f"http://127.0.0.1:{config.PORT}")
    try:
        status = client.get("/api/status").json()
        assert client.post("/api/rescan").status_code == 403
        headers = {"X-App-Token": status["token"]}
        assert client.post("/api/rescan", headers={**headers, "Origin": "https://example.com"}).status_code == 403
        assert client.get("/api/status", headers={"Host": "evil.example"}).status_code == 403
        asset = client.get("/api/assets?kind=texture").json()["items"][0]
        assert client.post(f"/api/assets/{asset['id']}/jobs", headers=headers, json={"purpose": "export", "format": "glb"}).status_code == 400
        job = client.post(f"/api/assets/{asset['id']}/jobs", headers=headers, json={"purpose": "export", "format": "png"}).json()
        for _ in range(100):
            job = client.get(f"/api/jobs/{job['id']}").json()
            if job["state"] not in ("queued", "running"):
                break
            time.sleep(0.02)
        assert job["state"] == "done", job
        response = client.get(job["url"], headers={"Range": "bytes=0-7"})
        assert response.status_code == 206
        assert response.content == b"\x89PNG\r\n\x1a\n"
        assert "attachment" in response.headers["content-disposition"]
        assert client.get("/api/jobs/unknown/file").status_code == 404
    finally:
        module.manager.close()
        client.close()
