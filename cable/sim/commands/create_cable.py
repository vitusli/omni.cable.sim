"""omni.kit.commands wrapper for build_cable — provides Undo/Redo."""

from __future__ import annotations

import carb
import omni.kit.commands
import omni.usd

class CreateCableCommand(omni.kit.commands.Command):
    """Create a volume-deformable cable.

    The command's ``do()`` schedules :func:`build_cable_async` and returns the
    anticipated root path immediately.  The async cook + attachment steps
    finish over subsequent Kit frames.

    Args:
        spec: A CableSpec instance (or dict of CableSpec fields).
    """

    def __init__(self, spec=None, **kwargs):
        from ..core.spec import CableSpec

        if spec is None:
            spec = CableSpec(**kwargs)
        elif isinstance(spec, dict):
            spec = CableSpec(**{**spec, **kwargs})
        self._spec = spec
        self._created_path: str = ""

    def do(self) -> str:
        from ..builder.cable_builder import build_cable

        self._created_path = build_cable(self._spec)
        return self._created_path

    def undo(self) -> None:
        if not self._created_path:
            return
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return
        # The cable root lives under its CableSim group Xform.  Removing the
        # group removes the whole cable (Cable, Start, End, Looks) at once.
        group_path = "/".join(self._created_path.split("/")[:-1]) or "/"
        if group_path not in ("", "/") and stage.GetPrimAtPath(group_path).IsValid():
            stage.RemovePrim(group_path)
            carb.log_info(f"[cable.sim] Removed cable group {group_path}")
        elif stage.GetPrimAtPath(self._created_path).IsValid():
            # Fallback: no group parent — remove just the root.
            stage.RemovePrim(self._created_path)
            carb.log_info(f"[cable.sim] Removed {self._created_path}")
        self._created_path = ""
