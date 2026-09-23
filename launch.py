"""Start the local application once and open its browser interface."""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

from server import config


def healthy():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{config.PORT}/api/status", timeout=2) as response:
            return json.load(response).get("source") == str(config.REMIX)
    except (OSError, ValueError):
        return False


def main():
    if healthy():
        webbrowser.open(f"http://127.0.0.1:{config.PORT}")
        return
    missing = [name for name, path in (("Blender", config.BLENDER), ("RTX IO extractor", config.EXTRACTOR)) if not path.exists()]
    if config.FFMPEG == "ffmpeg":
        missing.append("FFmpeg on PATH (or set HL2RTX_FFMPEG)")
    if missing:
        raise RuntimeError("Missing dependencies: " + ", ".join(missing))
    config.DATA.mkdir(exist_ok=True)
    with (config.DATA / "server.log").open("a", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", str(config.PORT), "--log-level", "warning"], cwd=config.APP, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    for _ in range(80):
        if healthy():
            (config.DATA / "server.pid").write_text(str(process.pid))
            webbrowser.open(f"http://127.0.0.1:{config.PORT}")
            print(f"Asset browser running at http://127.0.0.1:{config.PORT}")
            return
        if process.poll() is not None:
            raise RuntimeError("The app could not start. See data/server.log. The local port may already be in use.")
        time.sleep(0.25)
    raise RuntimeError("The server is taking longer than expected. See data/server.log.")


if __name__ == "__main__":
    main()
