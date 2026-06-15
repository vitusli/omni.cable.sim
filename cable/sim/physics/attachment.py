"""Auto attachment between deformable cable and rigid anchor."""

from __future__ import annotations

import carb
from pxr import Usd, Sdf

from .usd_utils import set_prim_attribute


def create_auto_attachment(
    stage: Usd.Stage,
    *,
    attachment_path: str,
    deformable_path: str,
    target_path: str,
    overlap_offset: float,
) -> bool:
    """Create an auto attachment via deformableUtils and set overlap offset.

    The actual API signature is positional:
        create_auto_deformable_attachment(stage, target_attachment_path,
                                          attachable0_path, attachable1_path)

    Returns True on success.
    """
    from omni.physx.scripts import deformableUtils

    try:
        ok = deformableUtils.create_auto_deformable_attachment(
            stage,
            Sdf.Path(attachment_path),
            Sdf.Path(deformable_path),
            Sdf.Path(target_path),
        )
        if not ok:
            carb.log_error(
                f"[cable.sim] create_auto_deformable_attachment returned False "
                f"({attachment_path})"
            )
            return False
    except Exception as exc:
        carb.log_error(
            f"[cable.sim] create_auto_deformable_attachment failed "
            f"({attachment_path}): {exc}"
        )
        return False

    attach_prim = stage.GetPrimAtPath(attachment_path)
    if not attach_prim.IsValid():
        carb.log_error(
            f"[cable.sim] attachment prim missing after creation: {attachment_path}"
        )
        return False

    set_prim_attribute(
        attach_prim,
        "physxAutoDeformableAttachment:deformableVertexOverlapOffset",
        Sdf.ValueTypeNames.Float,
        float(overlap_offset),
    )
    return True
