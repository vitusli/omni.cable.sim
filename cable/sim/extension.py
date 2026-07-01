"""Extension lifecycle — registers omni.kit commands and opens the GUI."""

from __future__ import annotations

import carb
import omni.ext
import omni.kit.commands
import omni.kit.menu.utils
from omni.kit.menu.utils import MenuItemDescription

WINDOW_TITLE = "Cable Simulation"


class CableSimExtension(omni.ext.IExt):
    """cable.sim — procedural deformable cables."""

    def on_startup(self, ext_id: str) -> None:
        carb.log_info(f"[cable.sim] on_startup ({ext_id})")

        from .commands.create_cable import CreateCableCommand

        omni.kit.commands.register(CreateCableCommand)
        self._command_cls = CreateCableCommand

        from .stretch_monitor import CableStretchMonitor

        self._stretch_monitor = CableStretchMonitor()
        self._stretch_monitor.start()

        self._window = None

        # Menu entry under vtools
        self._menu_items = [
            MenuItemDescription(
                name=WINDOW_TITLE,
                ticked=True,
                ticked_fn=lambda: self._window is not None and self._window.visible,
                onclick_fn=lambda *_: self._toggle_window(),
            )
        ]
        omni.kit.menu.utils.add_menu_items(self._menu_items, name="vtools")
        carb.log_info(f"[cable.sim] added menu item for '{WINDOW_TITLE}'")

    def on_shutdown(self) -> None:
        carb.log_info("[cable.sim] on_shutdown")
        if getattr(self, "_stretch_monitor", None) is not None:
            self._stretch_monitor.stop()
            self._stretch_monitor = None
        if self._menu_items:
            omni.kit.menu.utils.remove_menu_items(self._menu_items, name="vtools")
        if self._window:
            self._window.destroy()
            self._window = None
        try:
            omni.kit.commands.unregister(self._command_cls)
        except Exception:
            pass

    def _toggle_window(self):
        if self._window is None:
            try:
                from .cable_window import CableSimWindow
                self._window = CableSimWindow()
            except Exception as e:
                carb.log_error(f"[cable.sim] Failed to create window: {e}")
                import traceback
                carb.log_error(traceback.format_exc())
        else:
            self._window.visible = not self._window.visible
