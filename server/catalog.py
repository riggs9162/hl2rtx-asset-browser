"""Persistent metadata catalog; scanning never converts asset payloads."""

import glob
import hashlib
import json
import re
import sqlite3
import threading
from pathlib import Path

from . import config
from .archives import Package, vpk_entries


def identity(kind, value):
    return hashlib.sha256(f"{kind}:{value.lower()}".encode()).hexdigest()[:24]


def readable(name):
    return re.sub(r"^(SM|SK|M|T)_", "", name).replace("_", " ")


class Catalog:
    """SQLite catalog with incremental file signatures and stable asset identifiers."""

    def __init__(self):
        config.DATA.mkdir(parents=True, exist_ok=True)
        self.path = config.DATA / "catalog.sqlite"
        self.lock = threading.Lock()
        self.status = {"scanning": False, "message": "Ready", "errors": []}
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, kind TEXT, name TEXT, path TEXT, chapter TEXT, scope TEXT, bytes INTEGER, meta TEXT)")
            db.execute("CREATE INDEX IF NOT EXISTS kind_chapter ON assets(kind,chapter)")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def scan(self):
        if not self.lock.acquire(blocking=False):
            return
        self.status = {"scanning": True, "message": "Reading asset directories", "errors": []}
        try:
            if not config.REMIX.exists():
                raise FileNotFoundError(f"Game folder unavailable: {config.REMIX}")
            rows = {}
            for package_path in sorted(config.REMIX.rglob("*.pkg")):
                self.status["message"] = f"Indexing {package_path.name}"
                try:
                    package = Package(package_path)
                    for i, name in enumerate(package.names):
                        virtual = str(package_path.parent / name)
                        meta = dict(package=str(package_path), index=i, virtual=virtual, **package.metadata(i))
                        self.add(rows, "texture", virtual, name, package_path.stat().st_size, meta)
                except Exception as error:
                    self.status["errors"].append(f"{package_path.name}: {error}")
            for path in config.REMIX.rglob("*"):
                if not path.is_file():
                    continue
                ext = path.suffix.lower()
                rel = path.relative_to(config.REMIX).as_posix()
                if ext in (".usd", ".usda", ".usdc"):
                    scope = "model" if "/assets/" in rel and "/models/" in rel else "scene"
                    self.add(rows, "mesh", str(path), rel, path.stat().st_size, {"file": str(path)}, scope)
                elif ext in (".dds", ".png", ".tga", ".jpg", ".jpeg"):
                    self.add(rows, "texture", str(path), rel, path.stat().st_size, {"file": str(path), "virtual": str(path)})
            self.status["message"] = "Reading USD material overrides"
            from pxr import Sdf
            contexts = {}
            for mod in sorted((config.REMIX / "mods").glob("*")):
                root = mod / "mod.usda"
                if not root.exists():
                    continue
                for layer_path in sorted(mod.glob("*.usda")):
                    layer = Sdf.Layer.FindOrOpen(str(layer_path))
                    if not layer:
                        continue

                    def visit(prim_path):
                        prim = layer.GetPrimAtPath(prim_path)
                        if prim and prim.HasInfo("references"):
                            for ref in prim.referenceList.GetAddedOrExplicitItems():
                                if ref.assetPath:
                                    target = str((layer_path.parent / ref.assetPath).resolve()).lower()
                                    context = dict(root=str(root), prim=str(prim_path), label=layer_path.stem.replace("hl2rtx_", "").replace("_", " "))
                                    entries = contexts.setdefault(target, [])
                                    if not any(c["prim"] == context["prim"] for c in entries):
                                        entries.append(context)

                    layer.Traverse("/", visit)
            for key, row in list(rows.items()):
                if row[1] == "mesh":
                    meta = json.loads(row[7])
                    meta["contexts"] = contexts.get(str(Path(meta["file"]).resolve()).lower(), [])
                    rows[key] = (*row[:7], json.dumps(meta))
            audio_seen = set()
            for mount in self.audio_mounts():
                try:
                    if mount.suffix.lower() == ".vpk":
                        for entry in vpk_entries(mount):
                            name = entry["member"]
                            if Path(name).suffix.lower() in (".wav", ".mp3", ".ogg") and name.lower() not in audio_seen:
                                audio_seen.add(name.lower())
                                self.add(rows, "audio", name, name, entry["length"] + entry["preload"], {"vpk": entry}, "sound")
                    elif mount.is_dir():
                        for path in (mount / "sound").rglob("*"):
                            if path.suffix.lower() in (".wav", ".mp3", ".ogg"):
                                name = path.relative_to(mount).as_posix()
                                if name.lower() not in audio_seen:
                                    audio_seen.add(name.lower())
                                    self.add(rows, "audio", name, name, path.stat().st_size, {"file": str(path)}, "sound")
                except Exception as error:
                    self.status["errors"].append(f"{mount.name}: {error}")
            with self.connect() as db:
                db.execute("DELETE FROM assets")
                db.executemany("INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)", rows.values())
            self.status["message"] = f"{len(rows):,} assets indexed"
        except Exception as error:
            self.status["errors"].append(str(error))
            self.status["message"] = "Source unavailable; existing catalog retained"
        finally:
            self.status["scanning"] = False
            self.lock.release()

    def add(self, rows, kind, key, path, size, meta, scope="asset"):
        asset_id = identity(kind, key)
        chapter = next((v for v in path.replace("\\", "/").split("/") if re.match(r"ch\d", v)), "Shared")
        if kind == "audio":
            parts = path.split("/")
            chapter = parts[1] if len(parts) > 2 else "Other sounds"
        name = Path(path).stem
        for suffix in (".rtex", ".a", ".n", ".r", ".m", ".e", ".h"):
            name = name.removesuffix(suffix)
        rows[asset_id] = (asset_id, kind, readable(name), path.replace("\\", "/"), chapter, scope, size, json.dumps(meta))

    def audio_mounts(self):
        info = config.GAME / "hl2rtx/gameinfo.txt"
        mounts = []
        if info.exists():
            for line in info.read_text().splitlines():
                line = line.split("//", 1)[0].strip()
                match = re.match(r'"?(game(?:\+[^\s"]+)?)"?\s+"?([^"\s]+)', line, re.I)
                if not match:
                    continue
                name = match[2].replace("|gameinfo_path|", "hl2rtx/").replace("|all_source_engine_paths|", "")
                path = config.GAME / name
                candidates = sorted(Path(p) for p in glob.glob(str(path))) if "*" in name else [path]
                for candidate in candidates:
                    if re.search(r"_\d{3}\.vpk$", candidate.name):
                        continue
                    if candidate.suffix == ".vpk" and not candidate.exists():
                        candidate = candidate.with_name(candidate.stem + "_dir.vpk")
                    if candidate.exists() and config.source_path(candidate) not in mounts:
                        mounts.append(candidate.resolve())
        return mounts or [config.GAME / "hl2rtx", *sorted((config.GAME / "hl2").glob("*_dir.vpk")), config.GAME / "hl2"]

    def get(self, asset_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        if not row:
            raise KeyError("Asset not found")
        result = dict(row)
        result["meta"] = json.loads(result["meta"])
        return result

    def texture_map(self):
        with self.connect() as db:
            rows = db.execute("SELECT id,meta FROM assets WHERE kind='texture'").fetchall()
        return {str(Path(json.loads(r["meta"])["virtual"]).resolve()).lower(): r["id"] for r in rows}

    def search(self, kind, query="", chapter="", scope="", offset=0, limit=80):
        clauses, values = ["kind=?"], [kind]
        if query:
            for term in query.split():
                clauses.append("(name LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\')")
                escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                values.extend([f"%{escaped}%"] * 2)
        for field, value in (("chapter", chapter), ("scope", scope)):
            if value:
                clauses.append(f"{field}=?")
                values.append(value)
        where = " AND ".join(clauses)
        with self.connect() as db:
            count = db.execute(f"SELECT COUNT(*) FROM assets WHERE {where}", values).fetchone()[0]
            rows = db.execute(f"SELECT * FROM assets WHERE {where} ORDER BY name,id LIMIT ? OFFSET ?", [*values, limit, offset]).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            meta = json.loads(item.pop("meta"))
            item.update({k: meta[k] for k in ("width", "height", "format") if k in meta})
            items.append(item)
        return dict(items=items, total=count)

    def stats(self):
        with self.connect() as db:
            counts = {row[0]: row[1] for row in db.execute("SELECT kind,COUNT(*) FROM assets GROUP BY kind")}
            chapters = [dict(row) for row in db.execute("SELECT kind,chapter,COUNT(*) AS count FROM assets GROUP BY kind,chapter ORDER BY chapter")]
        return dict(counts=counts, chapters=chapters, **self.status)
