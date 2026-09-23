"""Loopback-only HTTP interface for the asset browser."""

import mimetypes
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .catalog import Catalog
from .jobs import JobManager

catalog = Catalog()
manager = JobManager(catalog)
TOKEN = secrets.token_urlsafe(32)


@asynccontextmanager
async def lifespan(app):
    threading.Thread(target=catalog.scan, daemon=True).start()
    stop = threading.Event()

    def maintain():
        while not stop.wait(300):
            manager.prune()

    threading.Thread(target=maintain, daemon=True).start()
    yield
    stop.set()
    manager.close()


app = FastAPI(title="Half-Life 2 RTX Asset Browser", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def local_only(request: Request, call_next):
    host = request.headers.get("host", "")
    if host not in (f"127.0.0.1:{config.PORT}", f"localhost:{config.PORT}"):
        return JSONResponse({"detail": "Only local requests are allowed"}, status_code=403)
    if request.method in ("POST", "DELETE", "PUT", "PATCH"):
        if request.headers.get("x-app-token") != TOKEN:
            return JSONResponse({"detail": "Refresh the app before continuing"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin not in (f"http://127.0.0.1:{config.PORT}", f"http://localhost:{config.PORT}"):
            return JSONResponse({"detail": "Invalid origin"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/api/status")
def status():
    return dict(**catalog.stats(), token=TOKEN, version=config.VERSION, source=str(config.REMIX), dependencies=dict(blender=config.BLENDER.exists(), extractor=config.EXTRACTOR.exists(), ffmpeg=config.FFMPEG != "ffmpeg"))


@app.get("/api/assets")
def assets(kind: Literal["mesh", "texture", "audio"] = "mesh", q: str = "", chapter: str = "", scope: str = "", offset: int = 0, limit: int = 80):
    return catalog.search(kind, q[:200], chapter, scope, max(0, offset), min(200, max(1, limit)))


@app.get("/api/assets/{asset_id}")
def asset_detail(asset_id: str):
    try:
        asset = catalog.get(asset_id)
        meta = asset.pop("meta")
        return dict(**asset, dimensions={k: meta[k] for k in ("width", "height", "format", "mips") if k in meta}, contexts=meta.get("contexts", []))
    except KeyError:
        raise HTTPException(404, "Asset not found")


class JobRequest(BaseModel):
    purpose: Literal["preview", "export"]
    format: Literal["glb", "gltf", "png", "wav", "mp3"]
    appearance: int = Field(default=0, ge=-1, le=10000)
    normal: bool = True


@app.post("/api/assets/{asset_id}/jobs")
def submit(asset_id: str, body: JobRequest):
    try:
        return manager.submit(asset_id, body.purpose, body.format, body.appearance, body.normal).public()
    except KeyError:
        raise HTTPException(404, "Asset not found")
    except ValueError as error:
        raise HTTPException(400, str(error))


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = manager.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job.public()


@app.delete("/api/jobs/{job_id}")
def cancel(job_id: str):
    job = manager.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.state in ("queued", "running"):
        job.cancelled.set()
    return job.public()


@app.get("/api/jobs/{job_id}/file")
def job_file(job_id: str):
    job = manager.jobs.get(job_id)
    if not job or job.state != "done" or not job.result or not job.result.is_file():
        raise HTTPException(404, "Cached file expired. Request the asset again.")
    record = job.result.parent / "result.json"
    if job.purpose == "export":
        import json
        if time.time() - json.loads(record.read_text())["created"] > 86400:
            raise HTTPException(410, "This export expired. Request the asset again.")
    record.touch()
    asset = catalog.get(job.asset_id)
    name = re.sub(r'[^\w .()-]', "_", asset["name"])[:150] + job.result.suffix
    return FileResponse(job.result, media_type=mimetypes.guess_type(str(job.result))[0] or "application/octet-stream", filename=name if job.purpose == "export" else None, headers={"Cache-Control": "private, max-age=0"})


@app.post("/api/rescan")
def rescan():
    threading.Thread(target=catalog.scan, daemon=True).start()
    return {"message": "Scan requested"}


@app.delete("/api/cache")
def clear_cache():
    try:
        manager.clear()
        return {"message": "Cache cleared"}
    except ValueError as error:
        raise HTTPException(409, str(error))


if (config.APP / "dist").exists():
    app.mount("/", StaticFiles(directory=config.APP / "dist", html=True), name="frontend")
