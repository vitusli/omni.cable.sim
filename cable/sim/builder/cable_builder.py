"""Top-level orchestrator that builds a cable from a CableSpec.

Every cable is grouped under a dedicated ``CableSim`` Xform which carries the
``cableSim:isCable`` marker attribute.  This makes it trivial to find every
cable in a stage later on (see :func:`find_cable_groups`):

  /World
    /CableSim        Xform  (cableSim:isCable = True)  ← per-cable group / marker
      /Start          Xform (RigidBodyAPI, PhysxRigidBodyAPI) @ (length, 0, 0)
        /Cube         Mesh  (CollisionAPI, MeshCollisionAPI=convexHull)
      /End            Xform (RigidBodyAPI, PhysxRigidBodyAPI) @ (0, 0, 0)
        /Cube         Mesh  (CollisionAPI, MeshCollisionAPI=convexHull)
      /Looks          Scope
        /Cable        Material (UsdPreviewSurface — render material)
      /Cable          root  (deformable body hierarchy)
        /cooking_mesh Mesh  (cylinder source)
        /simulation_mesh    TetMesh (created by auto cooker at runtime)
        /collision_mesh     TetMesh (created by auto cooker at runtime)
        /attachmentStart    Scope (auto attachment Cable <-> Start)
        /attachmentEnd      Scope (auto attachment Cable <-> End)
        /CablePhysics       Material (OmniPhysicsDeformableMaterialAPI)

The auto pipeline (PhysxAutoDeformableBodyAPI) handles cooking at runtime.
We do NOT call cook_auto_deformable_body — that is for the non-auto pipeline.
"""

from __future__ import annotations

import carb
import omni.usd
from pxr import Usd, UsdGeom, Gf, Sdf

from ..core.spec import CableSpec
from ..geometry.cylinder import build_cylinder_along_x
from ..physics.deformable import create_volume_deformable
from ..physics.material import (
    create_deformable_material,
    bind_physics_material,
    create_render_material,
    bind_render_material,
)
from ..physics.rigid import create_anchor_rigid_body
from ..physics.attachment import create_auto_attachment


# ----------------------------------------------------------------------------
# Cable group marker
# ----------------------------------------------------------------------------
# Custom attribute stamped on every cable's group Xform.  Search a stage for
# all prims that carry this attribute (== True) to enumerate every cable.
CABLE_MARKER_ATTR = "cableSim:isCable"
REST_LENGTH_ATTR = "cableSim:restLength"
SIGNAL_THRESHOLD_ATTR = "cableSim:strainThreshold"
CRITICAL_THRESHOLD_ATTR = "cableSim:criticalStrainThreshold"
STARTUP_CALIBRATION_FRAMES_ATTR = "cableSim:startupCalibrationFrames"
MIN_REST_EDGE_LENGTH_ATTR = "cableSim:minRestEdgeLengthForStrain"

# Default name for the per-cable group Xform.
CABLE_GROUP_BASE = "/World/CableSim"

# Leaf name used for the per-cable group Xform.
CABLE_GROUP_NAME = "CableSim"


def _pick_unique_group_path_under(stage: Usd.Stage, parent_path: str) -> str:
    """Return an unused ``<parent>/CableSim`` (or ``CableSim_<n>``) path."""
    parent = parent_path.rstrip("/")
    base = f"{parent}/{CABLE_GROUP_NAME}"
    if not stage.GetPrimAtPath(base).IsValid():
        return base
    idx = 1
    while stage.GetPrimAtPath(f"{base}_{idx}").IsValid():
        idx += 1
    return f"{base}_{idx}"


def _pick_unique_group_path(stage: Usd.Stage) -> str:
    """Return an unused ``/World/CableSim`` (or ``CableSim_<n>``) path.

    Ensures ``/World`` exists first.
    """
    if not stage.GetPrimAtPath("/World").IsValid():
        UsdGeom.Xform.Define(stage, "/World")
    return _pick_unique_group_path_under(stage, "/World")


def _mark_cable_group(prim: Usd.Prim) -> None:
    """Stamp the ``cableSim:isCable`` marker attribute on *prim*.

    Uses a custom bool attribute so the whole cable group can be found later
    via a simple stage traversal (see :func:`find_cable_groups`).
    """
    attr = prim.GetAttribute(CABLE_MARKER_ATTR)
    if not attr.IsValid():
        attr = prim.CreateAttribute(
            CABLE_MARKER_ATTR, Sdf.ValueTypeNames.Bool, custom=True
        )
    attr.Set(True)


def _set_default_monitoring_attrs(prim: Usd.Prim, *, rest_length: float) -> None:
    """Ensure cable monitoring attributes exist on the cable group prim."""
    rest = prim.GetAttribute(REST_LENGTH_ATTR)
    if not rest.IsValid():
        rest = prim.CreateAttribute(
            REST_LENGTH_ATTR, Sdf.ValueTypeNames.Float, custom=True
        )
    rest.Set(float(rest_length))

    signal = prim.GetAttribute(SIGNAL_THRESHOLD_ATTR)
    if not signal.IsValid():
        signal = prim.CreateAttribute(
            SIGNAL_THRESHOLD_ATTR, Sdf.ValueTypeNames.Float, custom=True
        )
    if signal.Get() is None:
        signal.Set(0.03)

    critical = prim.GetAttribute(CRITICAL_THRESHOLD_ATTR)
    if not critical.IsValid():
        critical = prim.CreateAttribute(
            CRITICAL_THRESHOLD_ATTR, Sdf.ValueTypeNames.Float, custom=True
        )
    if critical.Get() is None:
        critical.Set(0.06)

    calibration = prim.GetAttribute(STARTUP_CALIBRATION_FRAMES_ATTR)
    if not calibration.IsValid():
        calibration = prim.CreateAttribute(
            STARTUP_CALIBRATION_FRAMES_ATTR,
            Sdf.ValueTypeNames.Int,
            custom=True,
        )
    if calibration.Get() is None:
        calibration.Set(30)

    min_edge_len = prim.GetAttribute(MIN_REST_EDGE_LENGTH_ATTR)
    if not min_edge_len.IsValid():
        min_edge_len = prim.CreateAttribute(
            MIN_REST_EDGE_LENGTH_ATTR,
            Sdf.ValueTypeNames.Float,
            custom=True,
        )
    if min_edge_len.Get() is None:
        min_edge_len.Set(1.0e-4)


def find_cable_groups(stage: Usd.Stage | None = None) -> list[Usd.Prim]:
    """Return every cable group Xform in *stage* (or the active stage).

    A prim is considered a cable group if it carries the
    ``cableSim:isCable`` marker attribute set to ``True``.
    """
    if stage is None:
        stage = omni.usd.get_context().get_stage()
    if stage is None:
        return []
    groups: list[Usd.Prim] = []
    for prim in stage.Traverse():
        attr = prim.GetAttribute(CABLE_MARKER_ATTR)
        if attr.IsValid() and attr.Get():
            groups.append(prim)
    return groups


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

    # ------------------------------------------------------------------
    # 0. Cable group Xform (carries the cableSim:isCable marker)
    #    Every prim this builder creates lives under this group so a whole
    #    cable can be found / selected / removed as a unit.  We always create
    #    a dedicated group Xform and never stamp the marker on a pre-existing
    #    prim (e.g. /World) the user happened to point at.
    # ------------------------------------------------------------------
    if spec.root_path:
        # Explicit root: build the group next to it and nest the root inside,
        # keeping the requested leaf name (e.g. /World/MyCable ->
        # /World/CableSim*/MyCable).
        requested = Sdf.Path(spec.root_path)
        leaf_name = requested.name or "Cable"
        parent_of_request = str(requested.GetParentPath())
        if parent_of_request in ("", "/"):
            parent_of_request = "/World"
            if not stage.GetPrimAtPath("/World").IsValid():
                UsdGeom.Xform.Define(stage, "/World")
        group_path = _pick_unique_group_path_under(stage, parent_of_request)
        root_path = f"{group_path}/{leaf_name}"
    else:
        group_path = _pick_unique_group_path(stage)
        root_path = f"{group_path}/Cable"

    group_prim = UsdGeom.Xform.Define(stage, group_path).GetPrim()
    _mark_cable_group(group_prim)
    _set_default_monitoring_attrs(group_prim, rest_length=spec.length)

    root_name = Sdf.Path(root_path).name  # e.g. "Cable"
    cooking_path = f"{root_path}/cooking_mesh"
    sim_mesh_path = f"{root_path}/simulation_mesh"
    coll_mesh_path = f"{root_path}/collision_mesh"
    physics_material_path = f"{root_path}/{root_name}Physics"
    # Anchors + Looks are placed under the cable group (the parent of the root).
    parent_path = group_path
    render_material_path = f"{parent_path}/Looks/{root_name}"

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
    # 3. Materials
    #    - Physics material  -> <group>/Cable/CablePhysics (physics purpose)
    #    - Render material    -> <group>/Looks/Cable        (default purpose)
    # ------------------------------------------------------------------
    create_deformable_material(
        stage,
        physics_material_path,
        density=spec.density,
        youngs_modulus=spec.youngs_modulus,
        poissons_ratio=spec.poissons_ratio,
        dynamic_friction=spec.dynamic_friction,
        static_friction=spec.static_friction,
    )
    bind_physics_material(stage, root_path, physics_material_path)

    UsdGeom.Scope.Define(stage, f"{parent_path}/Looks")
    create_render_material(stage, render_material_path)
    bind_render_material(stage, root_path, render_material_path)

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
        f"[cable.sim] Built cable at {root_path} (group {group_path}) "
        f"(length={spec.length}, radius={spec.radius}, "
        f"rings={spec.ring_count}, radial={spec.radial_segments})"
    )
    return root_path
