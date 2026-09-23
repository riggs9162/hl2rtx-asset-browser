# Validation on the installed Half-Life 2 RTX library

Verified on 23 September 2026. These are representative real-asset tests, not a claim that every asset in the installation has been converted.

## Catalog and conversion policy

- 11,161 indexed assets: 1,281 USD model/scene files, 4,294 unique packed/loose textures, and 5,586 sounds.
- The 15 RTX IO packages contain 4,344 directory entries before duplicate virtual paths are resolved. Later packages override earlier packages, matching NVIDIA's reverse-alphabetical lookup. Loose textures override package entries.
- Initial metadata scan measured about 5.5 seconds on this PC. No asset payload conversion occurs during indexing or search.
- Automated tests verify that search/indexing leaves the source unchanged and creates no converted files.
- Preview and export use distinct cache keys and quality settings. A 2048-pixel test texture becomes a 1024-pixel preview while its export remains 2048 pixels.

## Real-asset results

| Test | Result |
| --- | --- |
| Selective BC4, BC5, BC7 decoding | Passed using one-member temporary packages and preview mip levels |
| BC6 HDR preview | Passed; the app reports its 8-bit PNG limitation |
| Brick wall color PNG | Full 4096 × 4096 export succeeded |
| Brick wall normal PNG | Full-resolution export and 1024-pixel preview succeeded |
| Hemisphere-octahedral decoding | Matched the formula in the installation's `AperturePBR_Normal.mdl`; tested diagonal and axis directions |
| DirectX/OpenGL normal enum | Tested against the shipped MDL enum: 0 hemisphere-octahedral, 1 OpenGL, 2 DirectX |
| Radiator GLB | 14,394 vertices, 28,690 triangles, 1 material, 3 embedded images |
| Radiator glTF ZIP | Every referenced buffer and image exists in the archive |
| Combine camera GLB | 8,063 vertices, 15,272 triangles, 2 materials, 7 images, 1 skeleton |
| Camera skin bindings | GLB contains JOINTS/WEIGHTS attributes and a mesh skin reference; reimport into Blender produced an armature modifier |
| Lightbulb glass/emission | glTF transmission and IOR preserved as approximations; emissive-strength extension contains the authored strength of 5 |
| WAV and MP3 | Both downloads succeeded from a VPK sound; MP3 browser download verified |
| Audio seeking | HTTP range request returned 206 and exactly the requested 32 bytes |

The real camera's chapter override redirects skinning to a runtime-only skeleton. The converter restores the original model's authored skeleton relationship and weights before Blender import. A synthetic regression test covers this behavior.

Observed uncached export times included about 11 seconds for the radiator GLB, 15 seconds for its glTF ZIP, 19 seconds for the camera GLB, 2–3 seconds for 4096-pixel PNGs, and under 2 seconds for the short audio sample. These are observations on this machine, not latency guarantees.

## Automated and browser checks

- 23 Python tests passed, covering malformed/truncated archives, path traversal, mip isolation, full mip/tail retention, VPK preload/split/embedded payloads, no pre-conversion, cache invalidation, LRU/expiration, cancellation, duplicate jobs, missing drives, abandoned job cleanup, normal decoding, skeleton restoration, external material bindings, local-origin checks, and ranged downloads.
- Production TypeScript/Vite build passed. The 3D viewer is lazy-loaded separately from the initial interface.
- Browser checks at 1440 × 1000 and 390 × 844 passed with no page errors and no horizontal overflow.
- Model orbit/rendering, texture channel selection and zoom, audio metadata/playback controls, PNG/MP3 export controls, and file download were exercised.
- Settings dialog keyboard focus trapping and Escape dismissal were verified.
- No requests to outside hosts were made by the completed app. Fonts and assets are local.
- Read-only WebMCP search registration, valid results, and invalid-input rejection were tested in an injected registration harness. A native WebMCP browser implementation was unavailable.
- Launcher started the service, then reused the existing service on a second invocation.

One upstream test-client deprecation warning is emitted by the installed Starlette/httpx integration. It does not affect the running app. Vite reports that the lazy Three.js chunk exceeds its generic 500 KB warning threshold; it is approximately 157 KB compressed and does not load until a mesh preview is opened.

## Remaining fidelity boundaries

RTX path-traced shading cannot be reproduced exactly in a browser or standard glTF. Glass absorption, specialized diffuse layers, displacement, and unsupported material inputs are reported as conversion notes. No missing animations are reconstructed. The installed release references some absent chapter layers; layers without available geometry fail explicitly. PNG export currently targets ordinary 2D textures, not texture arrays or cubemaps.
