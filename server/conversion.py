"""On-demand texture, USD material, model, and audio conversion."""

import hashlib
import json
import math
import os
import subprocess
import time
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdSkel

from . import config
from .archives import Package, extract_vpk


def run_process(args, job, timeout=600):
    log_path = job.folder / "process.log"
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen([str(a) for a in args], stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        job.process = process
        start = time.monotonic()
        try:
            while process.poll() is None:
                job.check()
                if time.monotonic() - start > timeout:
                    raise TimeoutError("Conversion timed out. Try a smaller asset.")
                time.sleep(0.1)
            if process.returncode:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-1600:]
                raise RuntimeError(f"Converter failed ({process.returncode}): {tail}")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            job.process = None


def decode_image(path):
    try:
        image = Image.open(path)
        image.load()
        return image
    except NotImplementedError:
        import struct
        import texture2ddecoder
        data = Path(path).read_bytes()
        height, width = struct.unpack_from("<II", data, 12)
        dxgi = struct.unpack_from("<I", data, 128)[0]
        if dxgi not in (95, 96):
            raise
        return Image.frombytes("RGBA", (width, height), texture2ddecoder.decode_bc6(data[148:], width, height), "raw", "BGRA")


def normal_image(image, encoding):
    """Decode Remix's hemisphere-octahedral layout and DirectX/OpenGL encoding enum in bounded strips."""
    result = Image.new("RGB", image.size)
    for top in range(0, image.height, 256):
        bottom = min(image.height, top + 256)
        values = np.asarray(image.crop((0, top, image.width, bottom)).convert("RGB"), dtype=np.float32) / 255.0
        if encoding == 0:
            xy = values[:, :, :2] * 2 - 1
            x = (xy[:, :, 0] + xy[:, :, 1]) * 0.5
            y = (xy[:, :, 0] - xy[:, :, 1]) * 0.5
            z = 1 - np.abs(x) - np.abs(y)
            xyz = np.stack([x, -y, z], axis=-1)
            xyz /= np.maximum(np.linalg.norm(xyz, axis=-1, keepdims=True), 1e-8)
            values = xyz * 0.5 + 0.5
        elif encoding == 2:
            values[:, :, 1] = 1 - values[:, :, 1]
        result.paste(Image.fromarray((values.clip(0, 1) * 255).astype(np.uint8)), (0, top))
    return result


def texture(asset, output, job, preview, encoding=None):
    meta = asset["meta"]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    job.check()
    if "package" in meta:
        package = Package(config.source_path(meta["package"]))
        scratch = output.parent / (output.stem + "_source")
        scratch.mkdir(exist_ok=True)
        mini = scratch / "selected.pkg"
        package.select(meta["index"], mini, preview)
        job.note("Decoding selected texture")
        run_process([config.EXTRACTOR, mini, "-o", scratch, "--force", "--break", "--crc32"], job, 120)
        source = scratch / "selected.dds"
    else:
        source = config.source_path(meta["file"])
    image = decode_image(source)
    if preview:
        image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    if encoding is not None:
        if meta.get("format") == 141:
            encoding = 0
        image = normal_image(image, encoding)
    image.save(output)
    return output


def selected_stage(asset, appearance=0):
    path = config.source_path(asset["meta"]["file"])
    contexts = asset["meta"].get("contexts", [])
    if contexts and appearance >= 0:
        if appearance >= len(contexts):
            raise ValueError("Unknown appearance")
        context = contexts[appearance]
        mask = Usd.StagePopulationMask([Sdf.Path(context["prim"])])
        stage = Usd.Stage.OpenMasked(str(config.source_path(context["root"])), mask)
        stage.SetEditTarget(stage.GetSessionLayer())
        stage.DefinePrim(context["prim"], "Xform")
        stage.ExpandPopulationMask()
        for prim in list(stage.TraverseAll()):
            if prim.IsA(UsdShade.Material):
                stage.DefinePrim(prim.GetPath(), "Material")
    else:
        stage = Usd.Stage.Open(str(path))
    if not stage:
        raise ValueError("USD stage could not be opened")
    return stage


def material_source(material):
    for prim in Usd.PrimRange(material.GetPrim()):
        if prim.GetTypeName() == "Shader" and prim.GetAttribute("inputs:diffuse_color_constant"):
            return prim
    for prim in Usd.PrimRange(material.GetPrim()):
        if prim.GetTypeName() == "Shader" and any(prim.GetAttribute("inputs:" + name) for name in ("diffuse_texture", "normalmap_texture")):
            return prim
    for prim in Usd.PrimRange(material.GetPrim()):
        if prim.GetTypeName() == "Shader" and "AperturePBR" in str(prim.GetAttribute("info:mdl:sourceAsset").Get()):
            return prim
    return None


def resolve_texture(attr):
    value = attr.Get()
    if not isinstance(value, Sdf.AssetPath) or not value.path:
        return None
    if value.resolvedPath:
        return config.source_path(value.resolvedPath)
    for spec in attr.GetPropertyStack():
        if spec.HasDefaultValue() and isinstance(spec.default, Sdf.AssetPath) and spec.default.path:
            return config.source_path(Path(spec.layer.realPath).parent / spec.default.path)
    return None


def dependencies(asset, appearance):
    meta = asset["meta"]
    paths = []
    if asset["kind"] == "mesh":
        stage = selected_stage(asset, appearance)
        paths = [Path(l.realPath) for l in stage.GetUsedLayers() if l.realPath]
        for prim in stage.Traverse():
            if prim.GetTypeName() == "Shader":
                for attr in prim.GetAttributes():
                    if attr.GetTypeName() == Sdf.ValueTypeNames.Asset:
                        try:
                            p = resolve_texture(attr)
                            if p and p.exists():
                                paths.append(p)
                        except ValueError:
                            pass
        paths.extend(config.REMIX.rglob("*.pkg"))
    elif "package" in meta:
        paths = [Path(meta["package"])]
    elif "vpk" in meta:
        paths = [Path(meta["vpk"]["directory"]), Path(meta["vpk"]["archive"])]
    else:
        paths = [Path(meta["file"])]
    paths.extend([config.EXTRACTOR, config.EXTRACTOR.with_name("rtxio.dll"), config.BLENDER, Path(config.FFMPEG), config.APP / "requirements.txt"])
    signatures = []
    for path in sorted(set(paths)):
        stat = path.stat()
        signatures.append((str(path), stat.st_size, stat.st_mtime_ns))
    return signatures


def restore_source_skinning(stage, asset, appearance):
    """Restore authored model skinning where Remix redirects bindings to runtime-only skeletons."""
    contexts = asset["meta"].get("contexts", [])
    if not contexts or appearance < 0:
        return
    source = Usd.Stage.Open(str(config.source_path(asset["meta"]["file"])))
    source_root = source.GetDefaultPrim().GetPath()
    target_root = Sdf.Path(contexts[appearance]["prim"])
    for prim in source.Traverse():
        target_path = prim.GetPath().ReplacePrefix(source_root, target_root)
        target = stage.GetPrimAtPath(target_path)
        if not target:
            continue
        if prim.IsA(UsdSkel.Root):
            UsdSkel.Root.Define(stage, target_path)
        if prim.IsA(UsdGeom.Mesh) and UsdSkel.BindingAPI(prim).GetSkeletonRel().GetTargets():
            UsdSkel.BindingAPI.Apply(target)
            for attr in prim.GetAttributes():
                if "skel:" in attr.GetName() and attr.Get() is not None:
                    dest = target.CreateAttribute(attr.GetName(), attr.GetTypeName())
                    dest.Set(attr.Get())
                    for name in ("interpolation", "elementSize"):
                        if attr.HasMetadata(name):
                            dest.SetMetadata(name, attr.GetMetadata(name))
                    for sample in attr.GetTimeSamples():
                        dest.Set(attr.Get(sample), sample)
            for rel in prim.GetRelationships():
                if rel.GetName().startswith("skel:"):
                    targets = [p.ReplacePrefix(source_root, target_root) for p in rel.GetTargets()]
                    target.CreateRelationship(rel.GetName()).SetTargets(targets)


def model(asset, fmt, job, catalog, preview, appearance):
    job.note("Reading model and material bindings", 8)
    stage = selected_stage(asset, appearance)
    mesh_count = sum(p.IsA(UsdGeom.Mesh) for p in stage.Traverse())
    if not mesh_count:
        raise ValueError("This USD layer contains no available mesh geometry. Choose a model in the Models filter.")
    stage.SetEditTarget(stage.GetSessionLayer())
    restore_source_skinning(stage, asset, appearance)
    textures = catalog.texture_map()
    materials = [UsdShade.Material(p) for p in stage.Traverse() if p.IsA(UsdShade.Material)]
    warnings = []
    converted = {}
    glass_materials = {}
    emission_strengths = {}
    for n, material in enumerate(materials):
        job.check()
        shader = material_source(material)
        if not shader:
            warnings.append(f"{material.GetPrim().GetName()}: material has no recognized Remix inputs; retained native USD material.")
            continue
        values = {a.GetName()[7:]: a.Get() for a in shader.GetAttributes() if a.GetName().startswith("inputs:") and a.Get() is not None}
        translucent = "Translucent" in str(shader.GetAttribute("info:mdl:sourceAsset").Get())
        if translucent:
            glass_materials[material.GetPrim().GetName()] = {"ior": float(values.get("ior_constant", 1.5))}
            warnings.append(f"{material.GetPrim().GetName()}: RTX glass is approximated with glTF transmission; volume absorption and the diffuse layer may differ.")
        path = material.GetPath().AppendChild("BrowserPBR")
        pbr = UsdShade.Shader.Define(stage, path)
        pbr.CreateIdAttr("UsdPreviewSurface")
        color = values.get("diffuse_color_constant", Gf.Vec3f(1))
        pbr.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
        pbr.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(float(values.get("reflection_roughness_constant", 0.05 if translucent else 0.5)))
        pbr.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(float(values.get("metallic_constant", 0)))
        pbr.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(float(values.get("opacity_constant", 1)))
        emission = bool(values.get("enable_emission", False))
        if emission:
            strength = float(values.get("emissive_intensity", 1))
            color = values.get("emissive_color_constant", (1, 1, 1))
            pbr.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*(float(v) * strength for v in color)))
            mask_value = values.get("emissive_mask_texture")
            if isinstance(mask_value, Sdf.AssetPath) and mask_value.path:
                emission_strengths[material.GetPrim().GetName()] = strength
        material.CreateSurfaceOutput().ConnectToSource(pbr.ConnectableAPI(), "surface")
        material.CreateSurfaceOutput("mdl").DisconnectSource()
        uv = UsdShade.Shader.Define(stage, material.GetPath().AppendChild("BrowserUV"))
        uv.CreateIdAttr("UsdPrimvarReader_float2")
        uv.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
        slots = [("diffuse_texture", "diffuseColor", "rgb", True), ("normalmap_texture", "normal", "rgb", False), ("reflectionroughness_texture", "roughness", "r", False), ("metallic_texture", "metallic", "r", False)]
        if translucent:
            slots[0] = ("transmittance_texture", "diffuseColor", "rgb", True)
        if emission:
            slots.append(("emissive_mask_texture", "emissiveColor", "rgb", True))
        for source_name, dest_name, channel, srgb in slots:
            attr = shader.GetAttribute("inputs:" + source_name)
            if not attr:
                continue
            resolved = resolve_texture(attr)
            if not resolved:
                continue
            texture_id = textures.get(str(resolved).lower())
            if not texture_id:
                warnings.append(f"Missing texture: {resolved.name}")
                continue
            encoding = int(values.get("encoding", 0)) if dest_name == "normal" else None
            key = (texture_id, encoding)
            if key not in converted:
                out = job.folder / "textures" / (texture_id + (f"_normal{encoding}" if encoding is not None else "") + ".png")
                texture(catalog.get(texture_id), out, job, preview, encoding)
                converted[key] = out
            tex = UsdShade.Shader.Define(stage, material.GetPath().AppendChild("Browser_" + dest_name))
            tex.CreateIdAttr("UsdUVTexture")
            tex.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(str(converted[key])))
            tex.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set("sRGB" if srgb else "raw")
            tex.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(uv.ConnectableAPI(), "result")
            if dest_name == "normal":
                tex.CreateInput("scale", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(2, 2, 2, 1))
                tex.CreateInput("bias", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(-1, -1, -1, 0))
            if dest_name == "emissiveColor":
                color = values.get("emissive_color_constant", (1, 1, 1))
                strength = float(values.get("emissive_intensity", 1))
                tex.CreateInput("scale", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(*(float(v) * strength for v in color), 1))
            pbr.CreateInput(dest_name, Sdf.ValueTypeNames.Float if channel == "r" else Sdf.ValueTypeNames.Normal3f if dest_name == "normal" else Sdf.ValueTypeNames.Color3f).ConnectToSource(tex.ConnectableAPI(), channel)
            if dest_name == "diffuseColor" and not translucent and not values.get("thin_film_thickness_from_albedo_alpha", False):
                with Image.open(converted[key]) as color_image:
                    has_alpha = "A" in color_image.getbands() and color_image.getchannel("A").getextrema()[0] < 255
                if has_alpha and (values.get("enable_opacity", False) or values.get("use_legacy_alpha_state", True) or values.get("blend_enabled", False)):
                    pbr.CreateInput("opacity", Sdf.ValueTypeNames.Float).ConnectToSource(tex.ConnectableAPI(), "a")
                    if not values.get("blend_enabled", False):
                        pbr.CreateInput("opacityThreshold", Sdf.ValueTypeNames.Float).Set(float(values.get("alpha_test_reference_value", 0.5)))
        for feature in ("height_texture", "subsurface_transmittance_texture"):
            value = values.get(feature)
            if isinstance(value, Sdf.AssetPath) and value.path:
                warnings.append(f"{material.GetPrim().GetName()}: {feature.replace('_', ' ')} is not represented in glTF.")
        job.note(f"Preparing material {n + 1} of {len(materials)}", 10 + int(45 * (n + 1) / max(1, len(materials))))
    source = job.folder / "prepared.usdc"
    stage.Flatten().Export(str(source))
    output = job.folder / ("model.gltf" if fmt == "gltf" else "model.glb")
    manifest = job.folder / "blender.json"
    manifest.write_text(json.dumps(dict(source=str(source), output=str(output), format=fmt, preview=preview, glass_materials=glass_materials, emission_strengths=emission_strengths)), encoding="utf-8")
    job.note("Building Blender-compatible model", 65)
    run_process([config.BLENDER, "--background", "--factory-startup", "--threads", "4", "--python", config.APP / "server/blender_worker.py", "--", manifest], job, 900)
    report = job.folder / "model-report.json"
    if report.exists():
        job.details = json.loads(report.read_text())
    job.warnings = list(dict.fromkeys(warnings))
    if not output.exists():
        raise RuntimeError("Blender did not produce a model")
    if fmt == "gltf":
        zipped = job.folder / "model.zip"
        with zipfile.ZipFile(zipped, "w", zipfile.ZIP_DEFLATED) as archive:
            for p in [output, *job.folder.glob("*.bin"), *job.folder.glob("*.png"), *job.folder.glob("*.jpg")]:
                archive.write(p, p.name)
        return zipped
    return output


def audio(asset, fmt, job, preview):
    meta = asset["meta"]
    extension = Path(asset["path"]).suffix.lower()
    source = job.folder / ("source" + extension)
    if "vpk" in meta:
        entry = dict(meta["vpk"])
        config.source_path(entry["archive"])
        config.source_path(entry["directory"])
        extract_vpk(entry, source)
    else:
        source = config.source_path(meta["file"])
    browser_compatible = extension in (".wav", ".mp3", ".ogg")
    if preview and extension == ".wav":
        import wave
        try:
            with wave.open(str(source)) as wav:
                browser_compatible = wav.getcomptype() == "NONE"
        except (wave.Error, EOFError):
            browser_compatible = False
    if (preview and browser_compatible) or (not preview and extension == "." + fmt):
        if source.parent == job.folder:
            return source
        import shutil
        output = job.folder / ("audio" + extension)
        shutil.copyfile(source, output)
        return output
    if preview:
        fmt = "wav"
    output = job.folder / ("audio." + fmt)
    options = ["-c:a", "libmp3lame", "-q:a", "2"] if fmt == "mp3" else ["-c:a", "pcm_s16le"]
    job.note("Converting audio", 45)
    run_process([config.FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", source, "-vn", *options, output], job, 300)
    return output
