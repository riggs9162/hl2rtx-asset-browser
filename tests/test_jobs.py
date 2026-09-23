"""On-demand behavior, invalidation, cancellation, and bounded cache tests."""

import json
import threading
import time

import numpy as np
import pytest
from PIL import Image

from server import config, conversion, jobs
from server.catalog import Catalog


@pytest.fixture
def local_library(tmp_path, monkeypatch):
    game = tmp_path / "game"
    remix = game / "rtx-remix"
    remix.mkdir(parents=True)
    (game / "hl2").mkdir()
    image = remix / "test.png"
    Image.new("RGB", (2048, 256), "red").save(image)
    monkeypatch.setattr(config, "GAME", game)
    monkeypatch.setattr(config, "REMIX", remix)
    monkeypatch.setattr(config, "DATA", tmp_path / "data")
    monkeypatch.setattr(conversion, "dependencies", lambda asset, appearance: [(image.stat().st_size, image.stat().st_mtime_ns)])
    catalog = Catalog()
    catalog.scan()
    manager = jobs.JobManager(catalog)
    yield catalog, manager, image
    manager.close()


def wait(job):
    end = time.monotonic() + 15
    while job.state in ("queued", "running") and time.monotonic() < end:
        time.sleep(0.01)
    assert job.state not in ("queued", "running"), job.message
    return job


def test_index_and_search_do_not_convert(local_library):
    catalog, manager, image = local_library
    before = image.read_bytes()
    assert catalog.search("texture", "test")["total"] == 1
    assert catalog.stats()["counts"]["texture"] == 1
    assert list(manager.cache.rglob("*.png")) == []
    assert manager.jobs == {}
    assert image.read_bytes() == before


def test_preview_and_export_have_separate_quality_and_cache(local_library):
    catalog, manager, image = local_library
    asset_id = catalog.search("texture")["items"][0]["id"]
    preview = wait(manager.submit(asset_id, "preview", "png"))
    export = wait(manager.submit(asset_id, "export", "png"))
    assert preview.state == export.state == "done"
    assert Image.open(preview.result).size == (1024, 128)
    assert Image.open(export.result).size == (2048, 256)
    assert preview.result != export.result
    cached = wait(manager.submit(asset_id, "preview", "png"))
    assert cached.message == "Ready from cache"
    Image.new("RGB", (2048, 256), "blue").save(image)
    changed = wait(manager.submit(asset_id, "preview", "png"))
    assert changed.result != preview.result
    assert Image.open(changed.result).getpixel((0, 0)) == (0, 0, 255)


def test_duplicate_requests_share_running_job_and_cancel(local_library, monkeypatch):
    catalog, manager, image = local_library
    entered = threading.Event()

    def slow(*args):
        job = args[2]
        entered.set()
        while True:
            job.check()
            time.sleep(0.01)

    monkeypatch.setattr(conversion, "texture", slow)
    asset_id = catalog.search("texture")["items"][0]["id"]
    first = manager.submit(asset_id, "preview", "png")
    assert entered.wait(3)
    second = manager.submit(asset_id, "preview", "png")
    assert first.id == second.id
    first.cancelled.set()
    assert wait(first).state == "cancelled"
    assert not first.folder.exists()


def test_missing_source_error_and_catalog_retained(local_library):
    catalog, manager, image = local_library
    asset_id = catalog.search("texture")["items"][0]["id"]
    image.unlink()
    job = wait(manager.submit(asset_id, "preview", "png"))
    assert job.state == "error"
    config.REMIX.rmdir()
    catalog.scan()
    assert catalog.search("texture")["total"] == 1
    assert catalog.status["errors"]


def test_cache_expiration_and_lru(local_library, monkeypatch):
    catalog, manager, image = local_library
    monkeypatch.setattr(jobs, "CACHE_LIMITS", {"preview": 350, "export": 350})
    for purpose, name, age in (("preview", "old", 100), ("preview", "new", 1), ("export", "expired", 90000)):
        folder = manager.cache / purpose / name
        folder.mkdir(parents=True)
        (folder / "asset.png").write_bytes(bytes(170))
        record = folder / "result.json"
        record.write_text(json.dumps({"created": time.time() - age}))
        import os
        os.utime(record, (time.time() - age, time.time() - age))
    manager.prune()
    assert not (manager.cache / "preview/old").exists()
    assert (manager.cache / "preview/new").exists()
    assert not (manager.cache / "export/expired").exists()


def test_restart_removes_abandoned_temporary_files(local_library):
    catalog, manager, image = local_library
    manager.close()
    abandoned = config.DATA / "temporary/abandoned"
    abandoned.mkdir(parents=True)
    (abandoned / "partial.glb").write_bytes(b"unfinished")
    restarted = jobs.JobManager(catalog)
    assert not abandoned.exists()
    restarted.close()


def test_normal_conversion_reconstructs_unit_vectors():
    source = Image.fromarray(np.array([[[128, 128, 0], [255, 255, 0]]], dtype=np.uint8))
    result = np.asarray(conversion.normal_image(source, 0), dtype=float) / 255 * 2 - 1
    assert np.linalg.norm(result[0, 0]) == pytest.approx(1, abs=.02)
    assert result[0, 0, 2] > .98
    assert result[0, 1, 0] > .98


def test_source_boundary_rejects_external_paths(local_library, tmp_path):
    with pytest.raises(ValueError):
        config.source_path(tmp_path / "outside.png")
