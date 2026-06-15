"""Volume (hex-mesh) deformable body creation via the auto pipeline.

Uses ``deformableUtils.create_auto_volume_deformable_hierarchy`` to set up the
deformable hierarchy (APIs, TetMesh prims, relationships).  Tet-mesh cooking
happens at runtime by the PhysX auto-cooker — no manual pre-cooking needed.

With the quad + n-gon cap mesh topology (matching Blender exports), the
auto-pipeline simplifier correctly preserves thin geometry at high resolution.
"""

from __future__ import annotations

import carb
from pxr import Usd, UsdGeom, Sdf

from .usd_utils import set_prim_attribute


def create_volume_deformable(
    stage: Usd.Stage,
    *,
    root_prim_path: str,
    cooking_src_mesh_path: str,
    simulation_mesh_path: str,
    collision_mesh_path: str,
    mass: float,
    self_collision: bool,
    self_collision_filter_distance: float,
    solver_position_iteration_count: int,
    linear_damping: float,
    contact_offset: float,
    rest_offset: float,
    hex_resolution: int,
) -> bool:
    """Build the deformable hierarchy on *root_prim_path*.

    Sets up APIs and empty TetMesh prims via the auto pipeline.  The PhysX
    runtime auto-cooker will cook conforming + voxel tet meshes on first
    simulation step (same code path as the UI "Create > Physics > Deformable
    (beta) > Volume" command).

    Returns True on success.
    """
    from omni.physx.scripts import deformableUtils

    # ------------------------------------------------------------------
    # 1. Create the hierarchy (APIs, empty TetMesh prims, relationships)
    # ------------------------------------------------------------------
    success = deformableUtils.create_auto_volume_deformable_hierarchy(
        stage=stage,
        root_prim_path=Sdf.Path(root_prim_path),
        simulation_tetmesh_path=Sdf.Path(simulation_mesh_path),
        collision_tetmesh_path=Sdf.Path(collision_mesh_path),
        cooking_src_mesh_path=Sdf.Path(cooking_src_mesh_path),
        simulation_hex_mesh_enabled=True,
        cooking_src_simplification_enabled=True,
        set_visibility_with_guide_purpose=True,
    )
    if not success:
        carb.log_error(
            f"[cable.sim] create_auto_volume_deformable_hierarchy failed at "
            f"{root_prim_path}"
        )
        return False

    root_prim = stage.GetPrimAtPath(root_prim_path)
    if not root_prim.IsValid():
        return False

    # ------------------------------------------------------------------
    # 2. Body attributes
    # ------------------------------------------------------------------
    set_prim_attribute(
        root_prim, "omniphysics:mass", Sdf.ValueTypeNames.Float, float(mass)
    )
    set_prim_attribute(
        root_prim,
        "physxDeformableBody:resolution",
        Sdf.ValueTypeNames.UInt,
        int(hex_resolution),
    )
    set_prim_attribute(
        root_prim,
        "physxDeformableBody:selfCollision",
        Sdf.ValueTypeNames.Bool,
        bool(self_collision),
    )
    set_prim_attribute(
        root_prim,
        "physxDeformableBody:selfCollisionFilterDistance",
        Sdf.ValueTypeNames.Float,
        float(self_collision_filter_distance),
    )
    set_prim_attribute(
        root_prim,
        "physxDeformableBody:solverPositionIterationCount",
        Sdf.ValueTypeNames.UInt,
        int(solver_position_iteration_count),
    )
    set_prim_attribute(
        root_prim,
        "physxDeformableBody:linearDamping",
        Sdf.ValueTypeNames.Float,
        float(linear_damping),
    )

    # Contact / rest offsets on the collision mesh
    coll_prim = stage.GetPrimAtPath(collision_mesh_path)
    if coll_prim.IsValid():
        coll_prim.ApplyAPI("PhysxCollisionAPI")
        set_prim_attribute(
            coll_prim,
            "physxCollision:contactOffset",
            Sdf.ValueTypeNames.Float,
            float(contact_offset),
        )
        set_prim_attribute(
            coll_prim,
            "physxCollision:restOffset",
            Sdf.ValueTypeNames.Float,
            float(rest_offset),
        )
    else:
        carb.log_warn(
            f"[cable.sim] collision mesh not found at {collision_mesh_path}"
        )

    carb.log_info(
        f"[cable.sim] Deformable hierarchy created at {root_prim_path} "
        f"(res={hex_resolution}, auto-cooking enabled)"
    )
    return True
