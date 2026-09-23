"""Regression coverage for Remix runtime skeleton redirects and normal encoding."""

import numpy as np
from PIL import Image
from pxr import Gf, Sdf, Usd, UsdGeom, UsdSkel, UsdShade, Vt

from server import config
from server.conversion import normal_image, restore_source_skinning, selected_stage


def test_runtime_skeleton_redirect_restores_source_weights(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GAME", tmp_path)
    model = tmp_path / "model.usda"
    source = Usd.Stage.CreateNew(str(model))
    root = UsdSkel.Root.Define(source, "/Model")
    source.SetDefaultPrim(root.GetPrim())
    skeleton = UsdSkel.Skeleton.Define(source, "/Model/Skeleton")
    skeleton.CreateJointsAttr().Set(Vt.TokenArray(["root"]))
    skeleton.CreateBindTransformsAttr().Set(Vt.Matrix4dArray([Gf.Matrix4d(1)]))
    skeleton.CreateRestTransformsAttr().Set(Vt.Matrix4dArray([Gf.Matrix4d(1)]))
    mesh = UsdGeom.Mesh.Define(source, "/Model/Mesh")
    mesh.CreatePointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(0), Gf.Vec3f(1, 0, 0), Gf.Vec3f(0, 1, 0)]))
    mesh.CreateFaceVertexCountsAttr().Set([3])
    mesh.CreateFaceVertexIndicesAttr().Set([0, 1, 2])
    binding = UsdSkel.BindingAPI.Apply(mesh.GetPrim())
    binding.CreateSkeletonRel().SetTargets([skeleton.GetPath()])
    binding.CreateJointIndicesPrimvar(False, 1).Set([0, 0, 0])
    binding.CreateJointWeightsPrimvar(False, 1).Set([1, 1, 1])
    source.GetRootLayer().Save()
    mod = tmp_path / "mod.usda"
    chapter = Usd.Stage.CreateNew(str(mod))
    ref = chapter.OverridePrim("/Root/meshes/item/replacement")
    ref.GetReferences().AddReference(str(model))
    target = chapter.OverridePrim(str(ref.GetPath()) + "/Mesh")
    target.CreateRelationship("skel:skeleton").SetTargets(["/Root/meshes/item/runtimeOnly"])
    chapter.GetRootLayer().Save()
    asset = {"meta": {"file": str(model), "contexts": [{"root": str(mod), "prim": str(ref.GetPath())}]}}
    stage = selected_stage(asset, 0)
    restore_source_skinning(stage, asset, 0)
    restored = stage.GetPrimAtPath(str(ref.GetPath()) + "/Mesh")
    target_path = UsdSkel.BindingAPI(restored).GetSkeletonRel().GetTargets()[0]
    assert stage.GetPrimAtPath(target_path).IsA(UsdSkel.Skeleton)
    assert UsdSkel.Root.Find(restored)
    assert list(UsdSkel.BindingAPI(restored).GetJointWeightsPrimvar().Get()) == [1, 1, 1]


def test_directx_and_opengl_normals_use_remix_enum():
    source = Image.fromarray(np.array([[[80, 200, 250]]], dtype=np.uint8))
    assert normal_image(source, 1).getpixel((0, 0)) == (80, 200, 250)
    assert normal_image(source, 2).getpixel((0, 0))[1] in (54, 55)


def test_mask_includes_material_bound_outside_model(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GAME", tmp_path)
    path = tmp_path / "mod.usda"
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.Xform.Define(stage, "/Root/Model")
    mesh = UsdGeom.Mesh.Define(stage, "/Root/Model/Mesh")
    material = UsdShade.Material.Define(stage, "/Looks/SharedMaterial")
    UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)
    stage.GetRootLayer().Save()
    asset = {"meta": {"file": str(path), "contexts": [{"root": str(path), "prim": "/Root/Model"}]}}
    result = selected_stage(asset, 0)
    assert result.GetPrimAtPath("/Looks/SharedMaterial").IsA(UsdShade.Material)
    assert any(p.GetPath() == "/Looks/SharedMaterial" for p in result.Traverse())


def test_hemioctahedral_diagonal_matches_shipped_mdl():
    source = Image.fromarray(np.array([[[255, 128, 0]]], dtype=np.uint8))
    result = np.asarray(normal_image(source, 0), dtype=float)[0, 0] / 255 * 2 - 1
    assert result[0] > .69
    assert result[1] < -.69
    assert abs(result[2]) < .02
