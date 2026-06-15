"""Top-level orchestrator that builds a cable from a CableSpec.

Produces a USD hierarchy matching the reference USDA:

  /World
    /Start          Xform (RigidBodyAPI, PhysxRigidBodyAPI) @ (length, 0, 0)
      /Cube         Mesh  (CollisionAPI, MeshCollisionAPI=convexHull)
    /End            Xform (RigidBodyAPI, PhysxRigidBodyAPI) @ (0, 0, 0)
      /Cube         Mesh  (CollisionAPI, MeshCollisionAPI=convexHull)
    /Cable          root  (deformable body hierarchy)
      /cooking_mesh Mesh  (cylinder source)
      /simulation_mesh    TetMesh (created by auto cooker at runtime)
      /collision_mesh     TetMesh (created by auto cooker at runtime)
      /attachmentStart    Scope (auto attachment Cable <-> Start)
      /attachmentEnd      Scope (auto attachment Cable <-> End)
      /Cable              Material (OmniPhysicsDeformableMaterialAPI)

The auto pipeline (PhysxAutoDeformableBodyAPI) handles cooking at runtime.
We do NOT call cook_auto_deformable_body — that is for the non-auto pipeline.
"""

from __future__ import annotations

import carb
import omni.usd
from pxr import Usd, UsdGeom, Gf, Sdf

from ..core.spec import CableSpec
from ..geometry.cylinder import build_cylinder_along_x
from ..physics.usd_utils import ensure_physics_scene_exists
from ..physics.deformable import create_volume_deformable
from ..physics.material import create_deformable_material, bind_physics_material
from ..physics.rigid import create_anchor_rigid_body
from ..physics.attachment import create_auto_attachment


def _pick_unique_root_path(stage: Usd.Stage) -> str:
    if not stage.GetPrimAtPath("/World").IsValid():
        UsdGeom.Xform.Define(stage, "/World")
    base = "/World/Cable"
    if not stage.GetPrimAtPath(base).IsValid():
        return base
    idx = 1
    while stage.GetPrimAtPath(f"{base}_{idx}").IsValid():
        idx += 1
    return f"{base}_{idx}"


def build_cable(spec: CableSpec, stage: Usd.Stage | None = None) -> str:
    """Build one volume-deformable cable in *stage* (or the active stage).

    Returns the USD path of the created cable root Xform, or "" on failure.

    Everything is synchronous.  The auto pipeline (PhysxAutoDeformableBodyAPI)
    cooks the tet meshes at runtime when PhysX processes the stage.
    """
    if stage is None:
        stage = omni.usd.get_context().get_stage()
    if stage is None:
        carb.log_error("[cable.sim] No active USD stage.")
        return ""

    ensure_physics_scene_exists(stage)

    root_path = spec.root_path or _pick_unique_root_path(stage)
    root_name = Sdf.Path(root_path).name  # e.g. "Cable"
    cooking_path = f"{root_path}/cooking_mesh"
    sim_mesh_path = f"{root_path}/simulation_mesh"
    coll_mesh_path = f"{root_path}/collision_mesh"
    material_path = f"{root_path}/{root_name}"
    parent_path = str(Sdf.Path(root_path).GetParentPath())

    # ------------------------------------------------------------------
    # 1. Root Xform + cooking source mesh
    # ------------------------------------------------------------------
    UsdGeom.Xform.Define(stage, root_path)
    # Mesh is centered at origin (-length/2 to +length/2) for the hex cooker.
    # No translate on root — anchors are placed accordingly.

    points, indices, counts = build_cylinder_along_x(
        length=spec.length,
        radius=spec.radius,
        radial_segments=spec.radial_segments,
        ring_count=spec.ring_count,
    )
    cooking = UsdGeom.Mesh.Define(stage, cooking_path)
    cooking.GetPointsAttr().Set(points)
    cooking.GetFaceVertexIndicesAttr().Set(indices)
    cooking.GetFaceVertexCountsAttr().Set(counts)
    cooking.GetSubdivisionSchemeAttr().Set("none")

    # ------------------------------------------------------------------
    # 2. Deformable hierarchy (auto pipeline — cooking happens at runtime)
    # ------------------------------------------------------------------
    ok = create_volume_deformable(
        stage,
        root_prim_path=root_path,
        cooking_src_mesh_path=cooking_path,
        simulation_mesh_path=sim_mesh_path,
        collision_mesh_path=coll_mesh_path,
        mass=spec.mass,
        self_collision=spec.self_collision,
        self_collision_filter_distance=spec.self_collision_filter_distance,
        solver_position_iteration_count=spec.solver_position_iteration_count,
        linear_damping=spec.linear_damping,
        contact_offset=spec.contact_offset,
        rest_offset=spec.rest_offset,
        hex_resolution=min(spec.ring_count, 100),
    )
    if not ok:
        return ""

    # ------------------------------------------------------------------
    # 3. Material
    # ------------------------------------------------------------------
    create_deformable_material(
        stage,
        material_path,
        density=spec.density,
        youngs_modulus=spec.youngs_modulus,
        poissons_ratio=spec.poissons_ratio,
        dynamic_friction=spec.dynamic_friction,
        static_friction=spec.static_friction,
    )
    bind_physics_material(stage, root_path, material_path)

    # ------------------------------------------------------------------
    # 4. Anchors + auto attachments
    #    These use PhysxAutoDeformableAttachmentAPI — resolved at runtime,
    #    no cooked data needed at authoring time.
    # ------------------------------------------------------------------
    if spec.create_start_anchor:
        start_path = f"{parent_path}/Start"
        if stage.GetPrimAtPath(start_path).IsValid():
            start_path = f"{parent_path}/{root_name}_Start"
        create_anchor_rigid_body(
            stage,
            start_path,
            position=Gf.Vec3f(spec.length / 2.0, 0.0, 0.0),
            size=spec.anchor_size,
            kinematic=spec.start_kinematic,
        )
        create_auto_attachment(
            stage,
            attachment_path=f"{root_path}/attachmentStart",
            deformable_path=root_path,
            target_path=start_path,
            overlap_offset=spec.attachment_overlap_offset,
        )

    if spec.create_end_anchor:
        end_path = f"{parent_path}/End"
        if stage.GetPrimAtPath(end_path).IsValid():
            end_path = f"{parent_path}/{root_name}_End"
        create_anchor_rigid_body(
            stage,
            end_path,
            position=Gf.Vec3f(-spec.length / 2.0, 0.0, 0.0),
            size=spec.anchor_size,
            kinematic=spec.end_kinematic,
        )
        create_auto_attachment(
            stage,
            attachment_path=f"{root_path}/attachmentEnd",
            deformable_path=root_path,
            target_path=end_path,
            overlap_offset=spec.attachment_overlap_offset,
        )

    carb.log_info(
        f"[cable.sim] Built cable at {root_path} "
        f"(length={spec.length}, radius={spec.radius}, "
        f"rings={spec.ring_count}, radial={spec.radial_segments})"
    )
    return root_path
