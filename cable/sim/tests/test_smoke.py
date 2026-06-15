"""Smoke tests for cable.sim."""

from __future__ import annotations

import omni.kit.test
import omni.usd

from cable.sim import CableSpec, build_cable


class TestCableSimSmoke(omni.kit.test.AsyncTestCase):
    async def setUp(self):
        await omni.usd.get_context().new_stage_async()

    async def test_default_cable_builds(self):
        path = build_cable(CableSpec())
        self.assertTrue(path.startswith("/World/Cable_"))

        stage = omni.usd.get_context().get_stage()
        self.assertTrue(stage.GetPrimAtPath(path).IsValid())
        self.assertTrue(stage.GetPrimAtPath(f"{path}/cooking_mesh").IsValid())
        self.assertTrue(stage.GetPrimAtPath(f"{path}/Start").IsValid())
        self.assertTrue(stage.GetPrimAtPath(f"{path}/End").IsValid())

    async def test_custom_dimensions(self):
        spec = CableSpec(length=2.0, radius=0.02, ring_count=50, radial_segments=12)
        path = build_cable(spec)
        self.assertNotEqual(path, "")
