# cable.sim — Overview

Procedural cable creation built on the Omniverse Beta deformable body schema.

## Public API

```python
from cable.sim import CableSpec, build_cable, CABLE_DEFAULTS
from cable.sim.builder import find_cable_groups, CABLE_MARKER_ATTR
```

## Generated USD hierarchy

Every cable is grouped under a dedicated `CableSim` Xform. That group Xform
carries the custom marker attribute `cableSim:isCable = True`, so all cables in
a stage can be found by traversing for that attribute.

```
/World/CableSim                    Xform  (custom bool cableSim:isCable = True)  ← marker
├── Cable                          Xform + deformable body hierarchy
│   ├── cooking_mesh               UsdGeom.Mesh   (procedural cylinder; source for cooker)
│   ├── simulation_mesh            UsdGeom.TetMesh (auto, hex-structured)
│   ├── collision_mesh             UsdGeom.TetMesh (auto) + PhysxCollisionAPI
│   ├── CablePhysics               UsdShade.Material (deformable material, bound at root)
│   ├── attachmentStart            Scope + PhysxAutoDeformableAttachmentAPI
│   └── attachmentEnd              Scope + PhysxAutoDeformableAttachmentAPI
├── Start                          Xform + UsdPhysics.RigidBodyAPI (kinematic)
│   └── Cube                       Mesh convex-hull collider
├── End                            Xform + UsdPhysics.RigidBodyAPI
│   └── Cube                       Mesh convex-hull collider
└── Looks                          Scope
    └── Cable                      UsdShade.Material (UsdPreviewSurface render material)
```

A second cable is created under `/World/CableSim_1`, a third under
`/World/CableSim_2`, and so on.

## Finding all cables in a stage

The `CableSim` group Xform of each cable carries `cableSim:isCable = True`.
Use the helper to enumerate them:

```python
from cable.sim.builder import find_cable_groups, CABLE_MARKER_ATTR

for group in find_cable_groups():          # active stage; pass a stage to override
    print(group.GetPath())                 # e.g. /World/CableSim, /World/CableSim_1

# Equivalent manual traversal:
for prim in stage.Traverse():
    attr = prim.GetAttribute(CABLE_MARKER_ATTR)
    if attr.IsValid() and attr.Get():
        ...  # this prim is a cable group
```

