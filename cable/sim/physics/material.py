"""Deformable material for the volume (hex) cable solver.

Matches the reference: only ``OmniPhysicsDeformableMaterialAPI``, all attrs
under the ``omniphysics:`` namespace, no elasticity damping.
"""

from __future__ import annotations

from pxr import Usd, UsdShade, Sdf, Gf

from .usd_utils import apply_usd_api_schema, set_prim_attribute


def create_deformable_material(
    stage: Usd.Stage,
    material_prim_path: str,
    *,
    density: float,
    youngs_modulus: float,
    poissons_ratio: float,
    dynamic_friction: float,
    static_friction: float,
) -> str:
    """Define a UsdShade.Material with ``OmniPhysicsDeformableMaterialAPI``."""
    mat_prim = UsdShade.Material.Define(stage, material_prim_path).GetPrim()

    apply_usd_api_schema(mat_prim, "OmniPhysicsDeformableMaterialAPI")

    set_prim_attribute(
        mat_prim, "omniphysics:density", Sdf.ValueTypeNames.Float, float(density)
    )
    set_prim_attribute(
        mat_prim,
        "omniphysics:dynamicFriction",
        Sdf.ValueTypeNames.Float,
        float(dynamic_friction),
    )
    set_prim_attribute(
        mat_prim,
        "omniphysics:staticFriction",
        Sdf.ValueTypeNames.Float,
        float(static_friction),
    )
    set_prim_attribute(
        mat_prim,
        "omniphysics:youngsModulus",
        Sdf.ValueTypeNames.Float,
        float(youngs_modulus),
    )
    set_prim_attribute(
        mat_prim,
        "omniphysics:poissonsRatio",
        Sdf.ValueTypeNames.Float,
        float(poissons_ratio),
    )

    return material_prim_path


def bind_physics_material(
    stage: Usd.Stage,
    target_prim_path: str,
    material_prim_path: str,
) -> None:
    """Bind *material_prim_path* to *target_prim_path* (physics purpose)."""
    target_prim = stage.GetPrimAtPath(target_prim_path)
    material = UsdShade.Material(stage.GetPrimAtPath(material_prim_path))
    binding = UsdShade.MaterialBindingAPI.Apply(target_prim)
    binding.Bind(
        material,
        bindingStrength=UsdShade.Tokens.weakerThanDescendants,
        materialPurpose="physics",
    )


def create_render_material(
    stage: Usd.Stage,
    material_prim_path: str,
    *,
    diffuse_color: tuple[float, float, float] = (0.2, 0.2, 0.2),
    roughness: float = 0.5,
    metallic: float = 0.0,
) -> str:
    """Define a UsdShade.Material with a ``UsdPreviewSurface`` shader.

    Mirrors the reference ``/World/Looks/Cable`` material so the cable has a
    visible render appearance independent of its physics material.
    """
    material = UsdShade.Material.Define(stage, material_prim_path)
    shader = UsdShade.Shader.Define(stage, f"{material_prim_path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput(
        "diffuseColor", Sdf.ValueTypeNames.Color3f
    ).Set(Gf.Vec3f(*diffuse_color))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(float(roughness))
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(float(metallic))

    surface_out = shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
    displacement_out = shader.CreateOutput("displacement", Sdf.ValueTypeNames.Token)
    material.CreateSurfaceOutput().ConnectToSource(surface_out)
    material.CreateDisplacementOutput().ConnectToSource(displacement_out)

    return material_prim_path


def bind_render_material(
    stage: Usd.Stage,
    target_prim_path: str,
    material_prim_path: str,
) -> None:
    """Bind a render *material_prim_path* to *target_prim_path*."""
    target_prim = stage.GetPrimAtPath(target_prim_path)
    material = UsdShade.Material(stage.GetPrimAtPath(material_prim_path))
    binding = UsdShade.MaterialBindingAPI.Apply(target_prim)
    binding.Bind(
        material,
        bindingStrength=UsdShade.Tokens.weakerThanDescendants,
    )
