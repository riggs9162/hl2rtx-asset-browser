"""Bounded conversion queues and independently managed preview/export caches."""

import concurrent.futures
import hashlib
import json
import shutil
import threading
import time
import uuid
from pathlib import Path

from . import config, conversion

CACHE_LIMITS = {"preview": 2 * 1024**3, "export": 10 * 1024**3}


class Cancelled(Exception):
    pass


class Job:
    """One explicit user request, including cancellation and progress."""

    def __init__(self, asset_id, purpose, fmt, appearance, normal):
        self.id = uuid.uuid4().hex
        self.asset_id, self.purpose, self.fmt = asset_id, purpose, fmt
        self.appearance, self.normal = appearance, normal
        self.state, self.message, self.progress = "queued", "Waiting for a worker", 0
        self.warnings, self.details = [], {}
        self.cancelled = threading.Event()
        self.folder = config.DATA / "temporary" / self.id
        self.folder.mkdir(parents=True)
        self.process = None
        self.result = None
        self.created = time.time()

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled("Cancelled")

    def note(self, message, progress=None):
        self.check()
        self.message = message
        if progress is not None:
            self.progress = progress

    def public(self):
        return dict(id=self.id, asset_id=self.asset_id, purpose=self.purpose, format=self.fmt, state=self.state, message=self.message, progress=self.progress, warnings=self.warnings, details=self.details, url=f"/api/jobs/{self.id}/file" if self.state == "done" else None)


class JobManager:
    """One model worker and one texture/audio worker; no speculative conversion."""

    def __init__(self, catalog):
        self.catalog = catalog
        self.jobs, self.requests = {}, {}
        self.lock = threading.RLock()
        self.heavy = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="mesh")
        self.light = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="media")
        self.cache = config.DATA / "cache"
        self.cache.mkdir(parents=True, exist_ok=True)
        temporary = config.DATA / "temporary"
        if temporary.exists():
            shutil.rmtree(temporary)
        self.prune()

    def submit(self, asset_id, purpose, fmt, appearance=0, normal=True):
        asset = self.catalog.get(asset_id)
        allowed = {"mesh": ("glb", "gltf"), "texture": ("png",), "audio": ("wav", "mp3")}
        if fmt not in allowed[asset["kind"]]:
            raise ValueError("Format does not match asset type")
        if asset["kind"] == "mesh" and purpose == "preview":
            fmt = "glb"
        key = (asset_id, purpose, fmt, appearance, normal)
        with self.lock:
            existing = self.requests.get(key)
            if existing and existing.state in ("queued", "running") and not existing.cancelled.is_set():
                return existing
            if sum(j.state in ("queued", "running") for j in self.jobs.values()) >= 20:
                raise ValueError("Queue is full. Wait for an export to finish.")
            job = Job(*key)
            self.jobs[job.id] = job
            self.requests[key] = job
            for old_id, old in list(self.jobs.items()):
                if old.state not in ("queued", "running") and time.time() - old.created > 86400:
                    self.jobs.pop(old_id, None)
            pool = self.heavy if asset["kind"] == "mesh" else self.light
            pool.submit(self.execute, job, asset)
            return job

    def execute(self, job, asset):
        try:
            job.check()
            job.state = "running"
            job.note("Checking source dependencies", 3)
            signature = conversion.dependencies(asset, job.appearance)
            code_signature = [(p.name, p.stat().st_mtime_ns) for p in Path(__file__).parent.glob("*.py")]
            key = hashlib.sha256(json.dumps([config.VERSION, code_signature, signature, job.asset_id, job.purpose, job.fmt, job.appearance, job.normal]).encode()).hexdigest()
            directory = self.cache / job.purpose / key
            record = directory / "result.json"
            if record.exists():
                result = json.loads(record.read_text())
                cached_file = directory / result["file"]
                if cached_file.exists() and (job.purpose != "export" or time.time() - result["created"] < 86400):
                    job.check()
                    job.result, job.warnings, job.details = cached_file, result["warnings"], result["details"]
                    record.touch()
                    job.state, job.message, job.progress = "done", "Ready from cache", 100
                    return
            preview = job.purpose == "preview"
            if asset["kind"] == "texture":
                name = asset["path"].lower()
                encoding = (0 if "oth_normal" in name else 2) if job.normal and any(t in name for t in ("normal", ".n.rtex")) else None
                output = conversion.texture(asset, job.folder / "texture.png", job, preview, encoding)
                if asset["meta"].get("format") == 143:
                    job.warnings.append("HDR texture converted to an 8-bit PNG; values outside the display range are not preserved.")
                if encoding is not None:
                    job.details["normal"] = "Blender / OpenGL tangent-space normal"
            elif asset["kind"] == "mesh":
                output = conversion.model(asset, job.fmt, job, self.catalog, preview, job.appearance)
            else:
                output = conversion.audio(asset, job.fmt, job, preview)
            job.check()
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / ("asset" + output.suffix)
            shutil.copyfile(output, target)
            result = dict(file=target.name, warnings=job.warnings, details=job.details, created=time.time())
            record.write_text(json.dumps(result), encoding="utf-8")
            job.result = target
            job.state, job.message, job.progress = "done", "Ready", 100
            self.prune(exclude=directory)
        except Cancelled:
            job.state, job.message = "cancelled", "Cancelled"
        except Exception as error:
            job.state, job.message = "error", str(error)
        finally:
            shutil.rmtree(job.folder, ignore_errors=True)

    def prune(self, exclude=None):
        with self.lock:
            for purpose, limit in CACHE_LIMITS.items():
                entries = []
                for record in (self.cache / purpose).glob("*/result.json"):
                    folder = record.parent
                    try:
                        stat = record.stat()
                        created = json.loads(record.read_text())["created"]
                        size = sum(p.stat().st_size for p in folder.iterdir() if p.is_file())
                        if purpose == "export" and time.time() - created > 86400 and folder != exclude:
                            shutil.rmtree(folder)
                        else:
                            entries.append((stat.st_mtime, size, folder))
                    except (OSError, ValueError, KeyError):
                        continue
                total = sum(e[1] for e in entries)
                for _, size, folder in sorted(entries):
                    if total <= limit:
                        break
                    if folder != exclude:
                        shutil.rmtree(folder, ignore_errors=True)
                        total -= size

    def clear(self):
        with self.lock:
            if any(j.state in ("queued", "running") for j in self.jobs.values()):
                raise ValueError("Wait for active jobs or cancel them before clearing the cache.")
            for purpose in ("preview", "export"):
                shutil.rmtree(self.cache / purpose, ignore_errors=True)

    def close(self):
        for job in list(self.jobs.values()):
            job.cancelled.set()
        self.heavy.shutdown(wait=True, cancel_futures=True)
        self.light.shutdown(wait=True, cancel_futures=True)
