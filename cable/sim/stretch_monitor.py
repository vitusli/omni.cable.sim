"""Runtime cable strain monitoring + debug visualization."""

from __future__ import annotations

from dataclasses import dataclass

import carb
import omni.kit.app
import omni.timeline
import omni.usd
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade


MARKER_ATTR_NAMES = ("cableSim:isCable", "isCable")

REST_LENGTH_ATTR = "cableSim:restLength"
SIGNAL_THRESHOLD_ATTR = "cableSim:strainThreshold"
CRITICAL_THRESHOLD_ATTR = "cableSim:criticalStrainThreshold"

DEFAULT_SIGNAL_THRESHOLD = 0.10
DEFAULT_CRITICAL_THRESHOLD = 0.20

EVENT_STRAIN_OVER = carb.events.type_from_string(
    "cable.sim.STRAIN_THRESHOLD_EXCEEDED"
)
EVENT_STRAIN_UNDER = carb.events.type_from_string(
    "cable.sim.STRAIN_THRESHOLD_UNDERSHOT"
)

DEBUG_MATERIAL_PATH = "/World/CableSimDebug/Looks/OverstrainRed"


@dataclass
class _CableState:
    rest_length: float
    over_signal_threshold: bool = False


class CableStretchMonitor:
    """Monitors cable strain and emits threshold crossing signals."""

    def __init__(self) -> None:
        self._update_sub = None
        self._message_bus = None
        self._states: dict[str, _CableState] = {}
        self._debug_active = False
        self._saved_bindings: dict[str, list[Sdf.Path] | None] = {}
        self._scan_counter = 0
        self._cached_marked_paths: list[str] = []

    def start(self) -> None:
        if self._update_sub is not None:
            return
        app = omni.kit.app.get_app()
        self._message_bus = app.get_message_bus_event_stream()
        self._update_sub = app.get_update_event_stream().create_subscription_to_pop(
            self._on_update, name="cable.sim.strain_monitor"
        )
        carb.log_info("[cable.sim] strain monitor started")

    def stop(self) -> None:
        if self._update_sub is not None:
            self._update_sub = None
        if self._debug_active:
            self._restore_debug_bindings()
        self._states.clear()
        self._cached_marked_paths = []
        carb.log_info("[cable.sim] strain monitor stopped")

    def _on_update(self, _event) -> None:
        timeline = omni.timeline.get_timeline_interface()
        if not timeline or not timeline.is_playing():
            return

        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return

        self._scan_counter = (self._scan_counter + 1) % 30
        if self._scan_counter == 0 or not self._cached_marked_paths:
            self._cached_marked_paths = [
                str(prim.GetPath()) for prim in self._find_marked_prims(stage)
            ]

        marked_prims = [
            stage.GetPrimAtPath(path)
            for path in self._cached_marked_paths
            if stage.GetPrimAtPath(path).IsValid()
        ]

        any_critical = False
        live_paths: set[str] = set()

        for prim in marked_prims:
            prim_path = str(prim.GetPath())
            live_paths.add(prim_path)
            start_prim, end_prim = self._find_endpoints(prim)
            if start_prim is None or end_prim is None:
                continue

            current_len = self._world_distance(stage, start_prim, end_prim)
            if current_len <= 1e-8:
                continue

            state = self._states.get(prim_path)
            if state is None:
                rest_length = self._get_rest_length(prim, current_len)
                state = _CableState(rest_length=rest_length)
                self._states[prim_path] = state

            if state.rest_length <= 1e-8:
                continue

            strain = (current_len - state.rest_length) / state.rest_length

            signal_threshold = self._get_threshold(
                prim, SIGNAL_THRESHOLD_ATTR, DEFAULT_SIGNAL_THRESHOLD
            )
            critical_threshold = self._get_threshold(
                prim, CRITICAL_THRESHOLD_ATTR, DEFAULT_CRITICAL_THRESHOLD
            )

            if strain >= signal_threshold and not state.over_signal_threshold:
                state.over_signal_threshold = True
                self._emit_signal(
                    EVENT_STRAIN_OVER,
                    prim_path,
                    strain,
                    signal_threshold,
                    state.rest_length,
                    current_len,
                )
            elif strain < signal_threshold and state.over_signal_threshold:
                state.over_signal_threshold = False
                self._emit_signal(
                    EVENT_STRAIN_UNDER,
                    prim_path,
                    strain,
                    signal_threshold,
                    state.rest_length,
                    current_len,
                )

            if strain >= critical_threshold:
                any_critical = True

        stale_paths = [path for path in self._states if path not in live_paths]
        for path in stale_paths:
            del self._states[path]

        current_paths = {str(prim.GetPath()) for prim in marked_prims}
        if any_critical and (
            not self._debug_active
            or current_paths != set(self._saved_bindings.keys())
        ):
            self._apply_debug_bindings(stage, marked_prims)
        elif not any_critical and self._debug_active:
            self._restore_debug_bindings()

    def _find_marked_prims(self, stage: Usd.Stage) -> list[Usd.Prim]:
        result: list[Usd.Prim] = []
        for prim in stage.Traverse():
            for attr_name in MARKER_ATTR_NAMES:
                attr = prim.GetAttribute(attr_name)
                if attr.IsValid() and bool(attr.Get()):
                    result.append(prim)
                    break
        return result

    def _find_endpoints(self, root: Usd.Prim) -> tuple[Usd.Prim | None, Usd.Prim | None]:
        start = root.GetChild("Start")
        end = root.GetChild("End")
        if start.IsValid() and end.IsValid():
            return start, end

        start_prim = None
        end_prim = None
        for child in Usd.PrimRange(root):
            name = child.GetName().lower()
            if start_prim is None and name.endswith("start"):
                start_prim = child
            if end_prim is None and name.endswith("end"):
                end_prim = child
            if start_prim is not None and end_prim is not None:
                break
        return start_prim, end_prim

    def _world_distance(self, stage: Usd.Stage, a: Usd.Prim, b: Usd.Prim) -> float:
        ta = self._world_position(stage, a)
        tb = self._world_position(stage, b)
        return float((ta - tb).GetLength())

    def _world_position(self, stage: Usd.Stage, prim: Usd.Prim) -> Gf.Vec3d:
        xformable = UsdGeom.Xformable(prim)
        matrix = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        return matrix.ExtractTranslation()

    def _get_rest_length(self, prim: Usd.Prim, fallback: float) -> float:
        attr = prim.GetAttribute(REST_LENGTH_ATTR)
        if attr.IsValid():
            value = attr.Get()
            if value is not None:
                return float(value)
        return float(fallback)

    def _get_threshold(self, prim: Usd.Prim, attr_name: str, default: float) -> float:
        attr = prim.GetAttribute(attr_name)
        if attr.IsValid():
            value = attr.Get()
            if value is not None:
                return float(value)
        return default

    def _emit_signal(
        self,
        event_type,
        cable_prim_path: str,
        strain: float,
        threshold: float,
        rest_length: float,
        current_length: float,
    ) -> None:
        payload = {
            "cablePath": cable_prim_path,
            "strain": float(strain),
            "threshold": float(threshold),
            "restLength": float(rest_length),
            "currentLength": float(current_length),
        }
        if self._message_bus is not None:
            self._message_bus.push(event_type, payload=payload)
        carb.log_info(f"[cable.sim] strain event {payload}")

    def _ensure_debug_material(self, stage: Usd.Stage) -> str:
        if not stage.GetPrimAtPath("/World").IsValid():
            UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Scope.Define(stage, "/World/CableSimDebug")
        UsdGeom.Scope.Define(stage, "/World/CableSimDebug/Looks")

        material = UsdShade.Material.Define(stage, DEBUG_MATERIAL_PATH)
        shader = UsdShade.Shader.Define(stage, f"{DEBUG_MATERIAL_PATH}/Shader")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(1.0, 0.0, 0.0)
        )
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.35)
        shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)

        surface_out = shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
        displacement_out = shader.CreateOutput("displacement", Sdf.ValueTypeNames.Token)
        material.CreateSurfaceOutput().ConnectToSource(surface_out)
        material.CreateDisplacementOutput().ConnectToSource(displacement_out)
        return DEBUG_MATERIAL_PATH

    def _apply_debug_bindings(self, stage: Usd.Stage, marked_prims: list[Usd.Prim]) -> None:
        if self._debug_active:
            self._restore_debug_bindings()

        debug_material_path = self._ensure_debug_material(stage)
        debug_material = UsdShade.Material(stage.GetPrimAtPath(debug_material_path))

        self._saved_bindings.clear()
        for prim in marked_prims:
            path = str(prim.GetPath())
            rel = prim.GetRelationship("material:binding")
            if rel.IsValid():
                self._saved_bindings[path] = list(rel.GetTargets())
            else:
                self._saved_bindings[path] = None

            binding_api = UsdShade.MaterialBindingAPI.Apply(prim)
            binding_api.Bind(
                debug_material,
                bindingStrength=UsdShade.Tokens.strongerThanDescendants,
            )

        self._debug_active = True
        carb.log_info(
            f"[cable.sim] critical strain detected, debug material bound to {len(marked_prims)} prim(s)"
        )

    def _restore_debug_bindings(self) -> None:
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return

        for prim_path, targets in self._saved_bindings.items():
            prim = stage.GetPrimAtPath(prim_path)
            if not prim.IsValid():
                continue
            rel = prim.GetRelationship("material:binding")
            if targets is None:
                if rel.IsValid():
                    prim.RemoveProperty("material:binding")
                continue
            if not rel.IsValid():
                rel = prim.CreateRelationship("material:binding")
            rel.SetTargets(targets)

        self._saved_bindings.clear()
        self._debug_active = False
        carb.log_info("[cable.sim] critical strain resolved, debug material restored")
