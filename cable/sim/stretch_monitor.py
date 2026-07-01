"""Runtime cable strain monitoring + debug visualization.

This monitor computes local strain from deformable simulation mesh data
(``simulation_mesh`` TetMesh points) and uses the edge with the highest
elongation as the cable strain signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import carb
import omni.kit.app
import omni.timeline
import omni.usd
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade


MARKER_ATTR_NAMES = ("cableSim:isCable", "isCable")

SIGNAL_THRESHOLD_ATTR = "cableSim:strainThreshold"
CRITICAL_THRESHOLD_ATTR = "cableSim:criticalStrainThreshold"
STARTUP_CALIBRATION_FRAMES_ATTR = "cableSim:startupCalibrationFrames"
MIN_REST_EDGE_LENGTH_ATTR = "cableSim:minRestEdgeLengthForStrain"

DEFAULT_SIGNAL_THRESHOLD = 0.03
DEFAULT_CRITICAL_THRESHOLD = 0.06
DEFAULT_STARTUP_CALIBRATION_FRAMES = 30
DEFAULT_MIN_REST_EDGE_LENGTH = 1.0e-4

EVENT_STRAIN_OVER = carb.events.type_from_string(
    "cable.sim.STRAIN_THRESHOLD_EXCEEDED"
)
EVENT_STRAIN_UNDER = carb.events.type_from_string(
    "cable.sim.STRAIN_THRESHOLD_UNDERSHOT"
)

DEBUG_MATERIAL_PATH = "/World/CableSimDebug/Looks/OverstrainRed"


@dataclass
class _CableState:
    over_signal_threshold: bool = False
    sample_count: int = 0
    baseline_strain: float | None = None


@dataclass
class _LocalStrainData:
    alert_strain: float
    percentile95_strain: float
    max_strain: float
    max_edge: tuple[int, int]
    max_edge_rest_length: float
    max_edge_current_length: float


class CableStretchMonitor:
    """Monitors local cable strain and emits threshold crossing signals."""

    def __init__(self) -> None:
        self._update_sub = None
        self._message_bus = None
        self._states: dict[str, _CableState] = {}
        self._debug_active = False
        self._saved_bindings: dict[str, list[Sdf.Path] | None] = {}
        self._scan_counter = 0
        self._cached_marked_paths: list[str] = []
        self._cleanup_stage_identifier: str | None = None

    def start(self) -> None:
        if self._update_sub is not None:
            return
        app = omni.kit.app.get_app()
        self._message_bus = app.get_message_bus_event_stream()
        self._update_sub = app.get_update_event_stream().create_subscription_to_pop(
            self._on_update, name="cable.sim.strain_monitor"
        )
        carb.log_info("[cable.sim] local strain monitor started")

    def stop(self) -> None:
        if self._update_sub is not None:
            self._update_sub = None
        if self._debug_active:
            self._restore_debug_bindings()
        self._states.clear()
        self._cached_marked_paths = []
        carb.log_info("[cable.sim] local strain monitor stopped")

    def _on_update(self, _event) -> None:
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return

        timeline = omni.timeline.get_timeline_interface()
        if not timeline:
            return

        if not timeline.is_playing():
            self._cleanup_stale_debug_bindings_for_stage(stage)
            if self._debug_active:
                self._restore_debug_bindings()
            if self._states:
                self._states.clear()
            return

        self._cleanup_stale_debug_bindings_for_stage(stage)

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

            strain_data = self._compute_local_max_strain(prim)
            if strain_data is None:
                continue

            state = self._states.get(prim_path)
            if state is None:
                state = _CableState()
                self._states[prim_path] = state

            signal_threshold = self._get_threshold(
                prim, SIGNAL_THRESHOLD_ATTR, DEFAULT_SIGNAL_THRESHOLD
            )
            critical_threshold = self._get_threshold(
                prim, CRITICAL_THRESHOLD_ATTR, DEFAULT_CRITICAL_THRESHOLD
            )
            startup_calibration_frames = int(
                self._get_threshold(
                    prim,
                    STARTUP_CALIBRATION_FRAMES_ATTR,
                    float(DEFAULT_STARTUP_CALIBRATION_FRAMES),
                )
            )

            effective_strain = self._effective_strain(
                state,
                strain_data.alert_strain,
                startup_calibration_frames,
            )
            self._log_startup_strain(
                prim_path,
                state,
                strain_data,
                effective_strain,
                startup_calibration_frames,
            )

            if effective_strain >= signal_threshold and not state.over_signal_threshold:
                state.over_signal_threshold = True
                self._emit_signal(
                    EVENT_STRAIN_OVER,
                    prim_path,
                    strain_data,
                    effective_strain,
                    signal_threshold,
                )
            elif effective_strain < signal_threshold and state.over_signal_threshold:
                state.over_signal_threshold = False
                self._emit_signal(
                    EVENT_STRAIN_UNDER,
                    prim_path,
                    strain_data,
                    effective_strain,
                    signal_threshold,
                )

            if effective_strain >= critical_threshold:
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

    def _compute_local_max_strain(self, cable_group_prim: Usd.Prim) -> _LocalStrainData | None:
        sim_prim = cable_group_prim.GetChild("Cable").GetChild("simulation_mesh")
        if not sim_prim.IsValid():
            return None

        sim_mesh = UsdGeom.TetMesh(sim_prim)
        if not sim_mesh:
            return None

        points_attr = sim_mesh.GetPointsAttr()
        rest_points_attr = sim_prim.GetAttribute("omniphysics:restShapePoints")
        tet_indices_attr = sim_mesh.GetTetVertexIndicesAttr()

        points = points_attr.Get()
        rest_points = rest_points_attr.Get() if rest_points_attr.IsValid() else None
        tet_indices = tet_indices_attr.Get()

        if not points or not rest_points or not tet_indices:
            return None

        if len(points) != len(rest_points):
            return None

        max_strain = -1.0
        max_edge = (0, 0)
        max_edge_rest = 0.0
        max_edge_cur = 0.0
        tensile_strains: list[float] = []
        min_rest_edge_length = self._get_threshold(
            cable_group_prim,
            MIN_REST_EDGE_LENGTH_ATTR,
            DEFAULT_MIN_REST_EDGE_LENGTH,
        )

        for tet in tet_indices:
            ids = [int(tet[0]), int(tet[1]), int(tet[2]), int(tet[3])]
            for i, j in combinations(ids, 2):
                if i < 0 or j < 0 or i >= len(points) or j >= len(points):
                    continue

                p_i = points[i]
                p_j = points[j]
                r_i = rest_points[i]
                r_j = rest_points[j]

                cur_len = float((p_i - p_j).GetLength())
                rest_len = float((r_i - r_j).GetLength())
                if rest_len <= float(min_rest_edge_length):
                    continue

                strain = (cur_len - rest_len) / rest_len
                if strain > 0.0:
                    tensile_strains.append(strain)
                if strain > max_strain:
                    max_strain = strain
                    max_edge = (i, j)
                    max_edge_rest = rest_len
                    max_edge_cur = cur_len

        if max_strain < 0.0:
            return None

        if tensile_strains:
            p95 = self._percentile(tensile_strains, 95.0)
        else:
            p95 = 0.0

        return _LocalStrainData(
            alert_strain=p95,
            percentile95_strain=p95,
            max_strain=max_strain,
            max_edge=max_edge,
            max_edge_rest_length=max_edge_rest,
            max_edge_current_length=max_edge_cur,
        )

    def _percentile(self, values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        if len(ordered) == 1:
            return ordered[0]
        p = max(0.0, min(100.0, percentile)) / 100.0
        pos = p * (len(ordered) - 1)
        lo = int(pos)
        hi = min(lo + 1, len(ordered) - 1)
        alpha = pos - lo
        return ordered[lo] * (1.0 - alpha) + ordered[hi] * alpha

    def _effective_strain(
        self,
        state: _CableState,
        raw_alert_strain: float,
        startup_calibration_frames: int,
    ) -> float:
        state.sample_count += 1
        if state.baseline_strain is None:
            state.baseline_strain = float(raw_alert_strain)

        if state.sample_count <= max(0, startup_calibration_frames):
            state.baseline_strain = max(float(state.baseline_strain), float(raw_alert_strain))

        return max(0.0, float(raw_alert_strain) - float(state.baseline_strain))

    def _log_startup_strain(
        self,
        prim_path: str,
        state: _CableState,
        strain_data: _LocalStrainData,
        effective_strain: float,
        startup_calibration_frames: int,
    ) -> None:
        if state.sample_count == 1:
            carb.log_info(
                "[cable.sim] startup local strain "
                f"path={prim_path} frame=1 p95={strain_data.percentile95_strain * 100.0:.3f}% "
                f"max={strain_data.max_strain * 100.0:.3f}%"
            )
            return

        if state.sample_count == max(60, startup_calibration_frames):
            carb.log_info(
                "[cable.sim] startup local strain "
                f"path={prim_path} frame={state.sample_count} p95={strain_data.percentile95_strain * 100.0:.3f}% "
                f"effective={effective_strain * 100.0:.3f}%"
            )

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
        strain_data: _LocalStrainData,
        effective_strain: float,
        threshold: float,
    ) -> None:
        payload = {
            "cablePath": cable_prim_path,
            "strain": float(effective_strain),
            "rawP95Strain": float(strain_data.percentile95_strain),
            "rawMaxEdgeStrain": float(strain_data.max_strain),
            "threshold": float(threshold),
            "mode": "local_p95_edge",
            "edgeVertex0": int(strain_data.max_edge[0]),
            "edgeVertex1": int(strain_data.max_edge[1]),
            "restEdgeLength": float(strain_data.max_edge_rest_length),
            "currentEdgeLength": float(strain_data.max_edge_current_length),
        }
        if self._message_bus is not None:
            self._message_bus.push(event_type, payload=payload)
        carb.log_info(f"[cable.sim] local strain event {payload}")

    def _ensure_debug_material(self, stage: Usd.Stage) -> str:
        if not stage.GetPrimAtPath("/World").IsValid():
            UsdGeom.Xform.Define(stage, "/World")
        if not stage.GetPrimAtPath("/World/CableSimDebug").IsValid():
            UsdGeom.Scope.Define(stage, "/World/CableSimDebug")
        if not stage.GetPrimAtPath("/World/CableSimDebug/Looks").IsValid():
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
            f"[cable.sim] critical local strain detected, debug material bound to {len(marked_prims)} prim(s)"
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
        self._remove_debug_material_if_present(stage)
        carb.log_info("[cable.sim] critical local strain resolved, debug material restored")

    def cleanup_stale_debug_bindings(self) -> None:
        """Remove stale debug material bindings left from previous sessions."""
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return

        self._cleanup_stale_debug_bindings_for_stage(stage, force=True)
        self._remove_debug_material_if_present(stage)

    def _cleanup_stale_debug_bindings_for_stage(
        self,
        stage: Usd.Stage,
        *,
        force: bool = False,
    ) -> None:
        root_layer = stage.GetRootLayer()
        stage_id = root_layer.identifier if root_layer is not None else ""
        if not force and stage_id == self._cleanup_stage_identifier:
            return
        self._cleanup_stage_identifier = stage_id

        for prim in stage.Traverse():
            rel = prim.GetRelationship("material:binding")
            if not rel.IsValid():
                continue
            targets = rel.GetTargets()
            if len(targets) == 1 and str(targets[0]) == DEBUG_MATERIAL_PATH:
                prim.RemoveProperty("material:binding")

        self._saved_bindings.clear()
        self._debug_active = False

    def _remove_debug_material_if_present(self, stage: Usd.Stage) -> None:
        if stage.GetPrimAtPath("/World/CableSimDebug").IsValid():
            stage.RemovePrim("/World/CableSimDebug")
