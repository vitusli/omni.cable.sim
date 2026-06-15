"""Declarative cable specification."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from .defaults import CABLE_DEFAULTS


@dataclass
class CableSpec:
    """All parameters needed to build one cable.

    A cable is created as a cylinder along +X starting at the origin (or at
    *root_path*'s local origin if the parent prim has a transform).
    """

    # Where to place it in the stage. If None, builder picks /World/Cable_<n>.
    root_path: Optional[str] = None

    # Geometry
    length: float = CABLE_DEFAULTS["length"]
    radius: float = CABLE_DEFAULTS["radius"]
    radial_segments: int = CABLE_DEFAULTS["radial_segments"]
    ring_count: int = CABLE_DEFAULTS["ring_count"]

    # Body
    mass: float = CABLE_DEFAULTS["mass"]
    self_collision: bool = CABLE_DEFAULTS["self_collision"]
    self_collision_filter_distance: float = CABLE_DEFAULTS[
        "self_collision_filter_distance"
    ]
    solver_position_iteration_count: int = CABLE_DEFAULTS[
        "solver_position_iteration_count"
    ]
    linear_damping: float = CABLE_DEFAULTS["linear_damping"]

    # Collision mesh offsets
    contact_offset: float = CABLE_DEFAULTS["contact_offset"]
    rest_offset: float = CABLE_DEFAULTS["rest_offset"]

    # Material
    density: float = CABLE_DEFAULTS["density"]
    youngs_modulus: float = CABLE_DEFAULTS["youngs_modulus"]
    poissons_ratio: float = CABLE_DEFAULTS["poissons_ratio"]
    dynamic_friction: float = CABLE_DEFAULTS["dynamic_friction"]
    static_friction: float = CABLE_DEFAULTS["static_friction"]

    # Anchors
    anchor_size: float = CABLE_DEFAULTS["anchor_size"]
    create_start_anchor: bool = CABLE_DEFAULTS["create_start_anchor"]
    create_end_anchor: bool = CABLE_DEFAULTS["create_end_anchor"]
    start_kinematic: bool = CABLE_DEFAULTS["start_kinematic"]
    end_kinematic: bool = CABLE_DEFAULTS["end_kinematic"]

    # Attachments
    attachment_overlap_offset: float = CABLE_DEFAULTS["attachment_overlap_offset"]

    def to_dict(self) -> dict:
        return asdict(self)
