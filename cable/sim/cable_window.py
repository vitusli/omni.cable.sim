"""GUI window exposing all CableSpec parameters."""

from __future__ import annotations

import omni.ui as ui
import omni.kit.commands

from .core.defaults import CABLE_DEFAULTS
from .core.spec import CableSpec


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

LABEL_WIDTH = 200
FIELD_WIDTH = ui.Fraction(1)
SPACING = 4


def _section_header(collapsed, title):
    """Custom header for CollapsableFrame."""
    with ui.HStack(height=22):
        ui.Spacer(width=4)
        with ui.VStack(width=10):
            ui.Spacer()
            if collapsed:
                tri = ui.Triangle(height=7, width=5)
                tri.alignment = ui.Alignment.RIGHT_CENTER
            else:
                tri = ui.Triangle(height=5, width=7)
                tri.alignment = ui.Alignment.CENTER_BOTTOM
            ui.Spacer()
        ui.Spacer(width=4)
        ui.Label(title, width=0, style={"font_size": 14})
        ui.Spacer(width=3)
        ui.Line()


def _float_field(label: str, default: float, tooltip: str = "", fmt: str = "%.4f"):
    """Float drag field with label. Returns the model."""
    with ui.HStack(height=22, spacing=8):
        ui.Label(label, width=LABEL_WIDTH, alignment=ui.Alignment.LEFT_CENTER, tooltip=tooltip)
        drag = ui.FloatDrag(width=FIELD_WIDTH, height=0, min=-1e12, max=1e12, step=0.001, format=fmt)
        drag.model.set_value(default)
    return drag.model


def _int_field(label: str, default: int, tooltip: str = ""):
    """Integer drag field with label. Returns the model."""
    with ui.HStack(height=22, spacing=8):
        ui.Label(label, width=LABEL_WIDTH, alignment=ui.Alignment.LEFT_CENTER, tooltip=tooltip)
        drag = ui.IntDrag(width=FIELD_WIDTH, height=0, min=1, max=100000)
        drag.model.set_value(default)
    return drag.model


def _checkbox(label: str, default: bool, tooltip: str = ""):
    """Checkbox with label. Returns the model."""
    with ui.HStack(height=22, spacing=8):
        ui.Label(label, width=LABEL_WIDTH, alignment=ui.Alignment.LEFT_CENTER, tooltip=tooltip)
        cb = ui.CheckBox(width=20, height=0)
        cb.model.set_value(default)
    return cb.model


def _string_field(label: str, default: str = "", tooltip: str = ""):
    """String field with label. Returns the model."""
    with ui.HStack(height=22, spacing=8):
        ui.Label(label, width=LABEL_WIDTH, alignment=ui.Alignment.LEFT_CENTER, tooltip=tooltip)
        sf = ui.StringField(width=FIELD_WIDTH, height=0)
        sf.model.set_value(default)
    return sf.model


def _collapsable(title: str, build_fn):
    with ui.CollapsableFrame(title, height=0, collapsed=False, build_header_fn=_section_header):
        with ui.VStack(spacing=SPACING):
            ui.Spacer(height=2)
            build_fn()
            ui.Spacer(height=2)


# ---------------------------------------------------------------------------
#  Window
# ---------------------------------------------------------------------------

WINDOW_TITLE = "Cable Simulation"


class CableSimWindow(ui.Window):
    """Main parameter window for cable.sim."""

    def __init__(self, **kwargs):
        super().__init__(WINDOW_TITLE, width=420, height=700, **kwargs)
        self._models: dict[str, ui.AbstractValueModel] = {}
        self.frame.set_build_fn(self._build_ui)

    def destroy(self):
        self._models.clear()
        super().destroy()

    # ------------------------------------------------------------------
    #  Collect current values into a CableSpec
    # ------------------------------------------------------------------

    def _get_spec(self) -> CableSpec:
        m = self._models
        root = m["root_path"].get_value_as_string().strip()
        return CableSpec(
            root_path=root if root else None,
            # Geometry
            length=m["length"].get_value_as_float(),
            radius=m["radius"].get_value_as_float(),
            radial_segments=m["radial_segments"].get_value_as_int(),
            ring_count=m["ring_count"].get_value_as_int(),
            # Body
            mass=m["mass"].get_value_as_float(),
            self_collision=m["self_collision"].get_value_as_bool(),
            self_collision_filter_distance=m["self_collision_filter_distance"].get_value_as_float(),
            solver_position_iteration_count=m["solver_position_iteration_count"].get_value_as_int(),
            linear_damping=m["linear_damping"].get_value_as_float(),
            # Collision mesh
            contact_offset=m["contact_offset"].get_value_as_float(),
            rest_offset=m["rest_offset"].get_value_as_float(),
            # Material
            density=m["density"].get_value_as_float(),
            youngs_modulus=m["youngs_modulus"].get_value_as_float(),
            # Anchors
            anchor_size=m["anchor_size"].get_value_as_float(),
            create_start_anchor=m["create_start_anchor"].get_value_as_bool(),
            create_end_anchor=m["create_end_anchor"].get_value_as_bool(),
            start_kinematic=m["start_kinematic"].get_value_as_bool(),
            end_kinematic=m["end_kinematic"].get_value_as_bool(),
            # Attachments
            attachment_overlap_offset=m["attachment_overlap_offset"].get_value_as_float(),
        )

    # ------------------------------------------------------------------
    #  Build
    # ------------------------------------------------------------------

    def _build_ui(self):
        d = CABLE_DEFAULTS
        m = self._models

        with ui.ScrollingFrame(horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF):
            with ui.VStack(spacing=6):
                ui.Spacer(height=2)

                # Root path
                m["root_path"] = _string_field(
                    "Root Path",
                    default="",
                    tooltip="Stage prim path (leave empty for auto /World/Cable_N)",
                )

                # --- Geometry ---
                def _geometry():
                    m["length"] = _float_field("Length", d["length"], "Cable length in meters")
                    m["radius"] = _float_field("Radius", d["radius"], "Cable radius in meters")
                    m["radial_segments"] = _int_field("Radial Segments", d["radial_segments"], "Number of radial segments")
                    m["ring_count"] = _int_field("Ring Count", d["ring_count"], "Number of rings along length")

                _collapsable("Geometry", _geometry)

                # --- Body ---
                def _body():
                    m["mass"] = _float_field("Mass", d["mass"], "Total mass in kg")
                    m["self_collision"] = _checkbox("Self Collision", d["self_collision"], "Enable self collision")
                    m["self_collision_filter_distance"] = _float_field(
                        "Self Collision Filter Dist", d["self_collision_filter_distance"], "Filter distance in meters"
                    )
                    m["solver_position_iteration_count"] = _int_field(
                        "Solver Position Iterations", d["solver_position_iteration_count"], "PhysX solver iterations"
                    )
                    m["linear_damping"] = _float_field("Linear Damping", d["linear_damping"], "Linear damping coefficient")

                _collapsable("Body", _body)

                # --- Collision Mesh ---
                def _collision():
                    m["contact_offset"] = _float_field("Contact Offset", d["contact_offset"], "Contact offset in meters")
                    m["rest_offset"] = _float_field("Rest Offset", d["rest_offset"], "Rest offset in meters")

                _collapsable("Collision Mesh", _collision)

                # --- Material ---
                def _material():
                    m["density"] = _float_field("Density", d["density"], "Density in kg/m^3")
                    m["youngs_modulus"] = _float_field(
                        "Young's Modulus", d["youngs_modulus"], "Young's modulus in Pa", fmt="%.1e"
                    )

                _collapsable("Material", _material)

                # --- Anchors ---
                def _anchors():
                    m["anchor_size"] = _float_field("Anchor Size", d["anchor_size"], "Cube scale for anchor colliders (m)")
                    m["create_start_anchor"] = _checkbox("Create Start Anchor", d["create_start_anchor"])
                    m["create_end_anchor"] = _checkbox("Create End Anchor", d["create_end_anchor"])
                    m["start_kinematic"] = _checkbox("Start Kinematic", d["start_kinematic"], "Fix start anchor in place")
                    m["end_kinematic"] = _checkbox("End Kinematic", d["end_kinematic"], "Fix end anchor in place")

                _collapsable("Anchors", _anchors)

                # --- Attachments ---
                def _attachments():
                    m["attachment_overlap_offset"] = _float_field(
                        "Overlap Offset", d["attachment_overlap_offset"], "Attachment overlap offset in meters"
                    )

                _collapsable("Attachments", _attachments)

                # --- Create Button ---
                ui.Spacer(height=4)
                ui.Button(
                    "Create Cable",
                    height=36,
                    clicked_fn=self._on_create,
                    style={"font_size": 16},
                )
                ui.Spacer(height=8)

    def _on_create(self):
        spec = self._get_spec()
        omni.kit.commands.execute("CreateCableCommand", spec=spec)
