"""Isolated Blender USD import and glTF export worker."""

import json
import re
import sys
from pathlib import Path

import bpy


def main():
    config = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.usd_import(filepath=config["source"], import_materials=True, import_cameras=False, import_lights=False, import_usd_preview=True, set_material_blend=True, import_skeletons=True, import_blendshapes=True)
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("No mesh geometry was imported")
    for material in bpy.data.materials:
        name = re.sub(r"\.\d{3}$", "", material.name)
        glass = config.get("glass_materials", {}).get(name)
        emission = config.get("emission_strengths", {}).get(name)
        if material.use_nodes:
            for node in material.node_tree.nodes:
                if node.type == "BSDF_PRINCIPLED":
                    if glass:
                        node.inputs["Transmission Weight"].default_value = 1
                        node.inputs["IOR"].default_value = glass["ior"]
                    if emission is not None:
                        node.inputs["Emission Strength"].default_value = emission
    report = dict(meshes=len(meshes), vertices=sum(len(obj.data.vertices) for obj in meshes), triangles=sum(sum(len(p.vertices) - 2 for p in obj.data.polygons) for obj in meshes), materials=[m.name for m in bpy.data.materials if m.users], skeletons=sum(o.type == "ARMATURE" for o in bpy.context.scene.objects), skinned_meshes=sum(any(m.type == "ARMATURE" for m in o.modifiers) for o in meshes), animations=len(bpy.data.actions))
    bpy.ops.export_scene.gltf(filepath=config["output"], export_format="GLTF_SEPARATE" if config["format"] == "gltf" else "GLB", export_yup=True, export_animations=True, export_skins=True, export_morph=True, export_image_format="AUTO", export_materials="EXPORT", export_cameras=False, export_lights=False)
    Path(config["output"]).with_name("model-report.json").write_text(json.dumps(report))
    print("ASSET_BROWSER_REPORT=" + json.dumps(report))


if __name__ == "__main__":
    main()
