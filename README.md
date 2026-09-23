# Half-Life 2 RTX Asset Browser

Open **Launch.cmd** to start the app at **http://127.0.0.1:8765**. The launcher reuses an already-running instance. The local service continues running after you close the browser.

## Browse and export

Choose Meshes, Textures, or Audio. Search names or source paths, filter by chapter or sound folder, then select an asset. Meshes default to reusable models; Scene layers also lists USD composition files, some of which have no standalone geometry.

Selecting an asset generates only its temporary preview. Export creates the full-quality file, then the export row offers a Download button. A preview is never used as the full-resolution export. No startup conversion, thumbnail sweep, bulk archive extraction, or speculative asset conversion occurs.

- Meshes: drag to orbit, scroll to zoom, right-drag to pan. Inspect materials, toggle wireframe, or change Appearance to use an authored chapter override. Source model omits chapter overrides. Available source animation clips have playback controls.
- Textures: inspect RGBA or individual channels and zoom. Blender normals converts octahedral/DirectX normal maps to ordinary OpenGL tangent-space PNGs. Uncheck it to inspect/export the stored decoded channels.
- Audio: native playback, seeking, and volume. WAV/MP3 files are copied without re-encoding when the chosen format matches. WAV conversion uses PCM16; MP3 conversion uses FFmpeg's high-quality VBR setting. Re-encoding compressed audio does not restore lost source quality.
- Downloads: GLB includes textures. glTF downloads as a ZIP with its buffers and images. PNG export retains original resolution. WAV and MP3 are also available.

## Storage and performance

The source installation is read-only. The catalog, caches, logs, and temporary files live in `data/` beside the application, never in the game folder.

The first scan reads directories, archive tables, and USD reference metadata. It does not unpack payloads. Further scanning can be requested from the library toolbar. RTX IO packages are addressed by file offset; only the selected texture's compressed blobs are copied into a temporary one-asset package for NVIDIA's extractor. Preview textures use existing mip levels where available and are capped at 1024 pixels.

There is one model worker and a separate texture/audio worker. The 3D renderer redraws on interaction or animation, caps pixel density, and releases GPU resources when changing assets. The mesh viewer is a separate lazy-loaded browser bundle.

Preview cache: 2 GB LRU. Export cache: 10 GB LRU and 24-hour expiration. An individual result larger than the cache budget remains available until the next maintenance pass. The settings panel clears both caches after active jobs finish or are cancelled. Downloaded files are not deleted. Cache keys include source and dependency modification times, conversion options, worker source versions, and converter binaries. Temporary jobs left by a crash are removed at the next startup.

## Installation and configuration

This copy is set up for the current PC. For a clean setup, run **Setup.ps1**, then **Launch.cmd**. Setup downloads pinned Python/web dependencies and NVIDIA RTX IO package version 7 with SHA-256 verification. It does not download or extract game assets.

Prerequisites: Windows, Python 3.13, Node.js 22 or newer, Blender 5.2, and FFmpeg. The configured game folder is `S:\SteamLibrary\steamapps\common\Half-Life 2 RTX`.

Optional environment variables:

| Variable | Purpose |
| --- | --- |
| `HL2RTX_GAME` | Game installation directory containing `rtx-remix`, `hl2rtx`, and `hl2` |
| `HL2RTX_BLENDER` | Full Blender executable path |
| `HL2RTX_FFMPEG` | Full FFmpeg executable path |
| `HL2RTX_PORT` | Local port, default 8765 |

The server binds only to 127.0.0.1. Mutation requests require a session token and a local origin. Archive names and source references are checked against the game installation boundary. There are no arbitrary file browsing endpoints and no telemetry. The finished interface, fonts, and converters work offline.

To stop the launched service, open **Stop.cmd**. Active conversions are interrupted; unfinished temporary files are removed on the next launch. `data/server.pid` records the process ID when started through the launcher. Diagnostics are in `data/server.log`.

## Fidelity and known boundaries

The converter uses OpenUSD composition and material bindings, then translates Remix inputs to USD Preview Surface for Blender's glTF exporter. Chapter appearances preserve the selected replacement's authored overrides. A material's displacement and specialized RTX shaders cannot be reproduced exactly by standard glTF; conversion notes identify omitted features and missing textures. Models retain source geometry, UVs, materials, available skeletons and animations; the app cannot reconstruct animations absent from the USD data.

The installed release references some chapter files that are not present. Unavailable geometry is reported as an error rather than replaced with a placeholder model. Texture PNG conversion supports ordinary 2D textures; cubemaps/texture arrays are reported as unsupported. BC6 HDR textures use an 8-bit display conversion for PNG and report the loss of HDR range.

Loose game assets take precedence over packed assets at the corresponding mount. Audio follows the installed `gameinfo.txt` search order and reads VPK directory/preload data and split archive payloads on demand.

## Development and validation

Run `.venv/Scripts/python.exe -m pytest tests` and `npm run build`. Start the production app with `.venv/Scripts/python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8765`.

See `VALIDATION.md` for the real-asset checks performed on this installation. No game assets are distributed with the source.

## Research and third-party components

- [NVIDIA RTX IO package layout](https://github.com/NVIDIAGameWorks/dxvk-remix/blob/main/src/dxvk/rtx_render/rtx_asset_package.h)
- [NVIDIA toolkit extractor integration](https://github.com/NVIDIAGameWorks/toolkit-remix/blob/main/source/extensions/lightspeed.trex.rtxio.core/lightspeed/trex/rtxio/core/core.py)
- [Blender USD support](https://docs.blender.org/manual/en/5.2/files/import_export/usd.html)
- [Blender glTF material support](https://docs.blender.org/manual/en/5.2/addons/scene_gltf2.html)

NVIDIA's unchanged SDK and license files reside in `tools/rtxio/` when installed. Python and web dependencies retain their upstream licenses. The bundled Barlow fonts use the SIL Open Font License, included in `public/fonts/OFL.txt`.
