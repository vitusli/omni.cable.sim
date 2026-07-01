"""Smoke tests for cable.sim."""

from __future__ import annotations

import omni.kit.test
import omni.usd

from cable.sim import CableSpec, build_cable
from cable.sim.builder import find_cable_groups, CABLE_MARKER_ATTR


class TestCableSimSmoke(omni.kit.test.AsyncTestCase):
    async def setUp(self):
        await omni.usd.get_context().new_stage_async()

    async def test_default_cable_builds(self):
        path = build_cable(CableSpec())
        # The cable root lives under a CableSim group Xform.
        self.assertTrue(path.startswith("/World/CableSim"))
        self.assertTrue(path.endswith("/Cable"))

        stage = omni.usd.get_context().get_stage()
        self.assertTrue(stage.GetPrimAtPath(path).IsValid())
        self.assertTrue(stage.GetPrimAtPath(f"{path}/cooking_mesh").IsValid())

        # Anchors + looks are siblings of the root, under the CableSim group.
        group_path = "/".join(path.split("/")[:-1])
        self.assertTrue(stage.GetPrimAtPath(f"{group_path}/Start").IsValid())
        self.assertTrue(stage.GetPrimAtPath(f"{group_path}/End").IsValid())

        # The group carries the cableSim:isCable marker.
        group_prim = stage.GetPrimAtPath(group_path)
        marker = group_prim.GetAttribute(CABLE_MARKER_ATTR)
        self.assertTrue(marker.IsValid())
        self.assertTrue(marker.Get())

    async def test_custom_dimensions(self):
        spec = CableSpec(length=2.0, radius=0.02, ring_count=50, radial_segments=12)
        path = build_cable(spec)
        self.assertNotEqual(path, "")

    async def test_find_cable_groups(self):
        build_cable(CableSpec())
        build_cable(CableSpec())
        groups = find_cable_groups()
        # Two distinct cable groups should be discoverable via the marker.
        self.assertEqual(len(groups), 2)
        paths = sorted(str(g.GetPath()) for g in groups)
        self.assertEqual(paths, ["/World/CableSim", "/World/CableSim_1"])

