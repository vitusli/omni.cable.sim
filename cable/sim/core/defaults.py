"""Default cable parameters mirroring the reference USDA.

Units: SI (meters, kilograms, Pascals).
"""

CABLE_DEFAULTS = {
    # Geometry (cylinder along +X at origin)
    "length": 1.5,
    "radius": 0.004,
    "radial_segments": 30,
    "ring_count": 150,

    # Body
    "mass": 4.0,
    "self_collision": True,
    "self_collision_filter_distance": 0.005,
    "solver_position_iteration_count": 64,
    "linear_damping": 10.0,

    # Collision mesh offsets
    "contact_offset": 0.004,
    "rest_offset": 0.002,

    # Material
    "density": 0.1,
    "youngs_modulus": 1.0e9,
    "poissons_ratio": 0.45,
    "dynamic_friction": 0.25,
    "static_friction": 0.5,

    # Anchors (rigid endpoint Xforms)
    "anchor_size": 0.1,             # cube scale (m) for anchor convex-hull colliders
    "create_start_anchor": True,
    "create_end_anchor": True,
    "start_kinematic": False,
    "end_kinematic": False,

    # Attachments
    "attachment_overlap_offset": 0.01,
}
