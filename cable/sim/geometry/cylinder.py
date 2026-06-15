"""Procedural cylinder mesh generator (axis along +X).

Produces quad sides + n-gon caps, matching the topology that Blender exports
and that the PhysX deformable mesh simplifier handles correctly.
"""

from __future__ import annotations

import math
from typing import Tuple, List

from pxr import Gf


def build_cylinder_along_x(
    length: float,
    radius: float,
    radial_segments: int = 30,
    ring_count: int = 150,
) -> Tuple[List[Gf.Vec3f], List[int], List[int]]:
    """Build a watertight closed cylinder centred at the origin along +X.

    Geometry runs from ``x = -length/2`` to ``x = +length/2``.

    Topology matches Blender cylinder export:
      - Side faces are **quads** (faceVertexCount = 4).
      - Each cap is a single **n-gon** (faceVertexCount = radial_segments).

    Args:
        length:          Total length along +X.
        radius:          Outer radius.
        radial_segments: Vertices around the circumference (>= 3).
        ring_count:      Number of rings along the length (>= 2).

    Returns:
        (points, face_vertex_indices, face_vertex_counts)
    """
    radial_segments = max(3, int(radial_segments))
    ring_count = max(2, int(ring_count))

    points: List[Gf.Vec3f] = []
    ring_starts: List[int] = []
    angle_step = 2.0 * math.pi / radial_segments
    dx = length / (ring_count - 1)
    half = length * 0.5

    # --- Side-ring vertices ---
    for i in range(ring_count):
        ring_starts.append(len(points))
        x = -half + i * dx
        for k in range(radial_segments):
            angle = k * angle_step
            y = math.cos(angle) * radius
            z = math.sin(angle) * radius
            points.append(Gf.Vec3f(x, y, z))

    indices: List[int] = []
    counts: List[int] = []

    # --- Start cap (x = -half) — single n-gon, normal points -X ---
    # Wind CW when viewed from -X  →  vertices in reverse order.
    base = ring_starts[0]
    for k in reversed(range(radial_segments)):
        indices.append(base + k)
    counts.append(radial_segments)

    # --- Side quads — outward-facing winding ---
    for i in range(ring_count - 1):
        a0 = ring_starts[i]
        a1 = ring_starts[i + 1]
        for k in range(radial_segments):
            kn = (k + 1) % radial_segments
            # Quad: bottom-left, bottom-right, top-right, top-left
            indices += [a0 + k, a0 + kn, a1 + kn, a1 + k]
            counts.append(4)

    # --- End cap (x = +half) — single n-gon, normal points +X ---
    base = ring_starts[-1]
    for k in range(radial_segments):
        indices.append(base + k)
    counts.append(radial_segments)

    return points, indices, counts
