"""Runtime stretch monitor for the cable_stretch.usd scene.

Use in Isaac Sim's Script Editor after opening:
    A:/OneDrive - Wandelbots GmbH/nvidia_omniverse/projects/DAVitus/playground/projekte_sidequests/cable/cable_stretch.usd

Press Play after running the script. The monitor latches the visual cable
material to red once any simulation tet reaches 20% principal stretch.
"""

from __future__ import annotations

import builtins
import traceback

import carb
import numpy as np
import omni.usd
from isaacsim.core.simulation_manager import IsaacEvents, SimulationManager
from pxr import Gf, Sdf, UsdShade


DEFORMABLE_ROOT = "/World/cable/Cable"
SHADER_PATH = "/World/Looks/Cable_vis/Shader"
COLOR_ATTR = "inputs:diffuseColor"

CRITICAL_STRETCH = 1.20
NORMAL_COLOR = Gf.Vec3f(0.33231598, 0.40200517, 0.45551604)
RED = Gf.Vec3f(1.0, 0.0, 0.0)

# Keep this at 1 while proving the setup. Increase to 2, 5, ... if Python SVD
# becomes too expensive for your scene.
CHECK_EVERY_N_PHYSICS_STEPS = 1

# Ignore the first few physics steps while PhysX finishes warm-up/readback.
WARMUP_PHYSICS_STEPS = 5

# Throttled diagnostics. Set to 0 to disable periodic logging.
LOG_EVERY_N_PHYSICS_STEPS = 30


def _as_numpy(value):
    """Convert numpy / torch / warp-like tensors to a CPU numpy array."""
    if isinstance(value, np.ndarray):
        return value
    if hasattr(value, "detach"):
        return value.detach().cpu().numpy()
    if hasattr(value, "cpu") and hasattr(value.cpu(), "numpy"):
        return value.cpu().numpy()
    if hasattr(value, "numpy"):
        return value.numpy()
    return np.asarray(value)


class CableStretchMonitor:
    def __init__(self):
        self.stage = None
        self.body_view = None
        self.inv_dm = None
        self.valid_tets = None
        self.callbacks = []
        self.step_count = 0
        self.triggered = False
        self.original_color = None
        self.failed = False
        self.max_baseline_stretch = 1.0
        self.last_max_stretch = 1.0
        self.last_relative_stretch = 1.0

    def start(self):
        self.stop()
        self.callbacks = [
            SimulationManager.register_callback(
                self._on_simulation_started,
                IsaacEvents.PHYSICS_READY,
            ),
            SimulationManager.register_callback(
                self._on_physics_post_step,
                IsaacEvents.POST_PHYSICS_STEP,
            ),
            SimulationManager.register_callback(
                self._on_simulation_stopped,
                IsaacEvents.TIMELINE_STOP,
            ),
        ]
        carb.log_info("[cable stretch] Monitor registered. Press Play to start.")

    def stop(self):
        for callback_id in self.callbacks:
            try:
                SimulationManager.deregister_callback(callback_id)
            except Exception:
                pass
        self.callbacks = []
        self.body_view = None
        self.inv_dm = None
        self.valid_tets = None
        self.step_count = 0
        self.failed = False
        self.max_baseline_stretch = 1.0
        self.last_max_stretch = 1.0
        self.last_relative_stretch = 1.0

    def _on_simulation_started(self, *_args):
        try:
            self._initialize_view()
        except Exception:
            carb.log_error("[cable stretch] Init failed:\n" + traceback.format_exc())
            self.failed = True

    def _on_simulation_stopped(self, *_args):
        self.body_view = None
        self.inv_dm = None
        self.valid_tets = None
        self.step_count = 0
        self.triggered = False
        self.failed = False
        self.max_baseline_stretch = 1.0
        self.last_max_stretch = 1.0
        self.last_relative_stretch = 1.0

    def _initialize_view(self):
        import omni.physics.tensors as tensors

        self.stage = omni.usd.get_context().get_stage()
        if self.stage is None:
            raise RuntimeError("No active USD stage.")
        if not self.stage.GetPrimAtPath(DEFORMABLE_ROOT).IsValid():
            raise RuntimeError(f"Deformable root not found: {DEFORMABLE_ROOT}")
        if not self.stage.GetPrimAtPath(SHADER_PATH).IsValid():
            raise RuntimeError(f"Shader not found: {SHADER_PATH}")

        self.body_view = self._create_body_view(tensors)
        rest_positions, tet_indices = self._read_rest_data_from_usd()

        rest_tets = rest_positions[tet_indices]
        dm = np.stack(
            (
                rest_tets[:, 1] - rest_tets[:, 0],
                rest_tets[:, 2] - rest_tets[:, 0],
                rest_tets[:, 3] - rest_tets[:, 0],
            ),
            axis=-1,
        )
        det = np.linalg.det(dm)
        valid = np.abs(det) > 1.0e-12
        if not np.any(valid):
            raise RuntimeError("No valid tet rest poses found.")

        self.valid_tets = tet_indices[valid]
        self.inv_dm = np.linalg.inv(dm[valid])
        self.original_color = self._get_shader_color()
        self._set_shader_color(NORMAL_COLOR)
        self.max_baseline_stretch = 1.0
        self.last_max_stretch = 1.0
        self.last_relative_stretch = 1.0

        carb.log_info(
            f"[cable stretch] Initialized {len(self.valid_tets)} tets; "
            f"threshold={CRITICAL_STRETCH:.3f}"
        )

    @staticmethod
    def _create_body_view(tensors):
        last_error = None
        for backend in ("torch", "numpy", "warp"):
            try:
                sim_view = tensors.create_simulation_view(backend)
                sim_view.set_subspace_roots("/")
                body_view = sim_view.create_volume_deformable_body_view(
                    DEFORMABLE_ROOT
                )
                carb.log_info(f"[cable stretch] Using tensor backend: {backend}")
                return body_view
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"Could not create a deformable tensor view: {last_error}")

    def _read_rest_data_from_usd(self):
        sim_mesh_path = f"{DEFORMABLE_ROOT}/simulation_mesh"
        sim_mesh = self.stage.GetPrimAtPath(sim_mesh_path)
        if not sim_mesh.IsValid():
            raise RuntimeError(f"Simulation mesh not found: {sim_mesh_path}")

        points_attr = sim_mesh.GetAttribute("omniphysics:restShapePoints")
        if not points_attr.IsValid() or points_attr.Get() is None:
            points_attr = sim_mesh.GetAttribute("points")

        indices_attr = sim_mesh.GetAttribute("omniphysics:restTetVtxIndices")
        if not indices_attr.IsValid() or indices_attr.Get() is None:
            indices_attr = sim_mesh.GetAttribute("tetVertexIndices")

        points = points_attr.Get()
        indices = indices_attr.Get()
        if points is None or indices is None:
            raise RuntimeError(f"Missing rest data on {sim_mesh_path}")

        rest_positions = np.asarray(
            [[float(p[0]), float(p[1]), float(p[2])] for p in points],
            dtype=np.float64,
        )

        raw_indices = list(indices)
        if raw_indices and hasattr(raw_indices[0], "__len__"):
            tet_indices = np.asarray(
                [[int(v) for v in tet] for tet in raw_indices],
                dtype=np.int64,
            )
        else:
            tet_indices = np.asarray(raw_indices, dtype=np.int64).reshape((-1, 4))

        return rest_positions, tet_indices

    def _on_physics_post_step(self, *_args):
        if self.failed:
            return
        if self.triggered:
            return

        self.step_count += 1
        if self.step_count % CHECK_EVERY_N_PHYSICS_STEPS != 0:
            return

        try:
            if self.body_view is None or self.inv_dm is None:
                self._initialize_view()

            max_stretch = self._measure_max_stretch()
            self.last_max_stretch = max_stretch
            if self.step_count <= WARMUP_PHYSICS_STEPS:
                self.max_baseline_stretch = max(
                    self.max_baseline_stretch,
                    max_stretch,
                )
                self.last_relative_stretch = 1.0
                self._log_status(max_stretch, 1.0, warmup=True)
                return

            relative_stretch = max_stretch / max(self.max_baseline_stretch, 1.0e-6)
            self.last_relative_stretch = relative_stretch
            self._log_status(max_stretch, relative_stretch, warmup=False)
            if relative_stretch >= CRITICAL_STRETCH:
                self._set_shader_color(RED)
                self.triggered = True
                carb.log_warn(
                    f"[cable stretch] Critical stretch reached: "
                    f"{relative_stretch:.4f}x relative "
                    f"(raw={max_stretch:.4f}, baseline={self.max_baseline_stretch:.4f}) "
                    f">= {CRITICAL_STRETCH:.4f}. "
                    f"{SHADER_PATH}.{COLOR_ATTR} set to red."
                )
        except Exception:
            carb.log_error("[cable stretch] Step failed:\n" + traceback.format_exc())
            self.failed = True

    def _log_status(self, max_stretch: float, relative_stretch: float, warmup: bool):
        if LOG_EVERY_N_PHYSICS_STEPS <= 0:
            return
        if warmup or self.step_count % LOG_EVERY_N_PHYSICS_STEPS == 0:
            phase = "warmup" if warmup else "running"
            carb.log_info(
                f"[cable stretch] step={self.step_count} phase={phase} "
                f"raw={max_stretch:.5f} baseline={self.max_baseline_stretch:.5f} "
                f"relative={relative_stretch:.5f} threshold={CRITICAL_STRETCH:.5f}"
            )

    def _measure_max_stretch(self) -> float:
        positions = _as_numpy(self.body_view.get_simulation_nodal_positions())[
            0
        ].astype(np.float64)
        current_tets = positions[self.valid_tets]
        ds = np.stack(
            (
                current_tets[:, 1] - current_tets[:, 0],
                current_tets[:, 2] - current_tets[:, 0],
                current_tets[:, 3] - current_tets[:, 0],
            ),
            axis=-1,
        )
        deformation_gradient = ds @ self.inv_dm
        principal_stretches = np.linalg.svd(
            deformation_gradient,
            compute_uv=False,
        )
        return float(np.max(principal_stretches))

    def _get_shader_color(self):
        attr = self.stage.GetPrimAtPath(SHADER_PATH).GetAttribute(COLOR_ATTR)
        return attr.Get() if attr.IsValid() else None

    def _set_shader_color(self, color):
        shader_prim = self.stage.GetPrimAtPath(SHADER_PATH)
        attr = shader_prim.GetAttribute(COLOR_ATTR)
        if not attr.IsValid():
            shader = UsdShade.Shader(shader_prim)
            attr = shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f)
        attr.Set(color)


def stop_cable_stretch_monitor():
    monitor = getattr(builtins, "_cable_stretch_monitor", None)
    if monitor is not None:
        monitor.stop()
        carb.log_info("[cable stretch] Monitor stopped.")


stop_cable_stretch_monitor()
builtins._cable_stretch_monitor = CableStretchMonitor()
builtins._cable_stretch_monitor.start()
builtins.stop_cable_stretch_monitor = stop_cable_stretch_monitor
builtins.get_cable_stretch_status = lambda: {
    "step": builtins._cable_stretch_monitor.step_count,
    "raw": builtins._cable_stretch_monitor.last_max_stretch,
    "baseline": builtins._cable_stretch_monitor.max_baseline_stretch,
    "relative": builtins._cable_stretch_monitor.last_relative_stretch,
    "threshold": CRITICAL_STRETCH,
    "triggered": builtins._cable_stretch_monitor.triggered,
    "failed": builtins._cable_stretch_monitor.failed,
}
