"""Low-level USD / OmniPhysics helpers."""

from __future__ import annotations

import carb
from pxr import Usd, UsdPhysics, Sdf


def apply_usd_api_schema(prim: Usd.Prim, schema_name: str) -> None:
    """Apply a USD API schema to *prim* by its string name.

    Always uses prim.ApplyAPI which correctly manages the apiSchemas
    TokenListOp.  Never fall back to manual metadata editing — that
    corrupts the list maintained by ApplyAPI / the C++ schema registry.
    """
    prim.ApplyAPI(schema_name)


def set_prim_attribute(
    prim: Usd.Prim,
    attr_name: str,
    type_name: Sdf.ValueTypeName,
    value,
) -> None:
    attr = prim.GetAttribute(attr_name)
    if not attr.IsValid():
        attr = prim.CreateAttribute(
            attr_name, type_name, variability=Sdf.VariabilityVarying
        )
    attr.Set(value)


def set_prim_relationship(
    prim: Usd.Prim,
    rel_name: str,
    target_paths: list[str],
) -> None:
    rel = prim.GetRelationship(rel_name)
    if not rel.IsValid():
        rel = prim.CreateRelationship(rel_name)
    rel.SetTargets([Sdf.Path(t) for t in target_paths])


def ensure_physics_scene_exists(
    stage: Usd.Stage, scene_path: str = "/World/PhysicsScene"
) -> str:
    """Guarantee a UsdPhysics.Scene exists at *scene_path*."""
    prim = stage.GetPrimAtPath(scene_path)
    if not prim.IsValid():
        UsdPhysics.Scene.Define(stage, scene_path)
        carb.log_info(f"[cable.sim] Created physics scene at {scene_path}")
    return scene_path
