"""Rigid body anchor (Xform with Mesh-based convex-hull cube collider).

Matches the reference USDA structure:
  <prim_path>  Xform  (PhysicsRigidBodyAPI, PhysxRigidBodyAPI)
    └─ Cube    Mesh   (PhysicsCollisionAPI, PhysicsMeshCollisionAPI=convexHull)
                       unit cube points, scale=(size, size, size)
"""

from __future__ import annotations

from pxr import Usd, UsdGeom, UsdPhysics, Gf, Sdf, Vt

from .usd_utils import apply_usd_api_schema


# Unit cube geometry (matches the reference exactly)
_CUBE_POINTS = [
    (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (-0.5, 0.5, 0.5), (0.5, 0.5, 0.5),
    (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (-0.5, 0.5, -0.5), (0.5, 0.5, -0.5),
]
_CUBE_FACE_VERTEX_COUNTS = [4, 4, 4, 4, 4, 4]
_CUBE_FACE_VERTEX_INDICES = [
    0, 1, 3, 2,  4, 6, 7, 5,  6, 2, 3, 7,
    4, 5, 1, 0,  4, 0, 2, 6,  5, 7, 3, 1,
]
_CUBE_NORMALS = [
    (0, 0, 1), (0, 0, 1), (0, 0, 1), (0, 0, 1),
    (0, 0, -1), (0, 0, -1), (0, 0, -1), (0, 0, -1),
    (0, 1, 0), (0, 1, 0), (0, 1, 0), (0, 1, 0),
    (0, -1, 0), (0, -1, 0), (0, -1, 0), (0, -1, 0),
    (-1, 0, 0), (-1, 0, 0), (-1, 0, 0), (-1, 0, 0),
    (1, 0, 0), (1, 0, 0), (1, 0, 0), (1, 0, 0),
]
_CUBE_UVS = [
    (0, 0), (1, 0), (1, 1), (0, 1),
    (1, 0), (1, 1), (0, 1), (0, 0),
    (0, 1), (0, 0), (1, 0), (1, 1),
    (0, 0), (1, 0), (1, 1), (0, 1),
    (0, 0), (1, 0), (1, 1), (0, 1),
    (1, 0), (1, 1), (0, 1), (0, 0),
]


def create_anchor_rigid_body(
    stage: Usd.Stage,
    prim_path: str,
    *,
    position: Gf.Vec3f,
    size: float,
    kinematic: bool,
) -> str:
    """Create an Xform rigid body with a Mesh-based convex-hull cube collider.

    Matches the reference USDA anchor structure exactly.
    """
    # Anchor Xform with full xformOps (translate, orient, scale)
    xform = UsdGeom.Xform.Define(stage, prim_path)
    xformable = UsdGeom.Xformable(xform)
    xformable.ClearXformOpOrder()
    xformable.AddTranslateOp().Set(Gf.Vec3d(position[0], position[1], position[2]))
    xformable.AddOrientOp(precision=UsdGeom.XformOp.PrecisionDouble).Set(Gf.Quatd(1, 0, 0, 0))
    xformable.AddScaleOp().Set(Gf.Vec3d(1, 1, 1))

    prim = xform.GetPrim()
    rb = UsdPhysics.RigidBodyAPI.Apply(prim)
    rb.CreateKinematicEnabledAttr(bool(kinematic))
    rb.CreateRigidBodyEnabledAttr(True)
    apply_usd_api_schema(prim, "PhysxRigidBodyAPI")  # both RigidBodyAPI + PhysxRigidBodyAPI

    # Cube collider child — Mesh prim with unit cube, scaled down
    cube_path = f"{prim_path}/Cube"
    mesh = UsdGeom.Mesh.Define(stage, cube_path)
    mesh.GetPointsAttr().Set([Gf.Vec3f(*p) for p in _CUBE_POINTS])
    mesh.GetFaceVertexCountsAttr().Set(_CUBE_FACE_VERTEX_COUNTS)
    mesh.GetFaceVertexIndicesAttr().Set(_CUBE_FACE_VERTEX_INDICES)
    mesh.GetNormalsAttr().Set([Gf.Vec3f(*n) for n in _CUBE_NORMALS])
    mesh.SetNormalsInterpolation("faceVarying")
    mesh.GetSubdivisionSchemeAttr().Set("none")

    # Extent
    mesh.GetExtentAttr().Set(
        Vt.Vec3fArray([Gf.Vec3f(-0.5, -0.5, -0.5), Gf.Vec3f(0.5, 0.5, 0.5)])
    )

    # UVs
    primvars_api = UsdGeom.PrimvarsAPI(mesh)
    uv_primvar = primvars_api.CreatePrimvar(
        "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying
    )
    uv_primvar.Set([Gf.Vec2f(*uv) for uv in _CUBE_UVS])

    # XformOps on cube: translate(0,0,0), orient(identity), scale(size)
    cube_xformable = UsdGeom.Xformable(mesh)
    cube_xformable.ClearXformOpOrder()
    cube_xformable.AddTranslateOp().Set(Gf.Vec3d(0, 0, 0))
    cube_xformable.AddOrientOp(precision=UsdGeom.XformOp.PrecisionDouble).Set(Gf.Quatd(1, 0, 0, 0))
    cube_xformable.AddScaleOp().Set(Gf.Vec3d(size, size, size))

    # Collision APIs
    cube_prim = mesh.GetPrim()
    UsdPhysics.CollisionAPI.Apply(cube_prim)
    mesh_coll = UsdPhysics.MeshCollisionAPI.Apply(cube_prim)
    mesh_coll.CreateApproximationAttr().Set("convexHull")

    return prim_path
