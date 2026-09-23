"""Local paths and runtime limits."""

import os
import shutil
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
GAME = Path(os.environ.get("HL2RTX_GAME", "S:/SteamLibrary/steamapps/common/Half-Life 2 RTX")).resolve()
REMIX = GAME / "rtx-remix"
DATA = APP / "data"
EXTRACTOR = APP / "tools/rtxio/bin/RtxIoResourceExtractor.exe"
BLENDER = Path(os.environ.get("HL2RTX_BLENDER", "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe"))
FFMPEG = os.environ.get("HL2RTX_FFMPEG", shutil.which("ffmpeg") or "ffmpeg")
VERSION = "1.0.0"
PORT = int(os.environ.get("HL2RTX_PORT", "8765"))


def source_path(path):
    value = Path(path).resolve()
    if not value.is_relative_to(GAME):
        raise ValueError("Asset reference is outside the game installation")
    return value
