# cable.sim — Overview

Procedural cable creation built on the Omniverse Beta deformable body schema.

## Public API

```python
from cable.sim import CableSpec, build_cable, CABLE_DEFAULTS
```

## Generated USD hierarchy

```
/World/Cable                       Xform + OmniPhysicsDeformableBodyAPI + PhysxBaseDeformableBodyAPI
├── cooking_mesh                   UsdGeom.Mesh   (procedural cylinder; source for cooker)
├── SimulationMesh                 UsdGeom.TetMesh (auto, hex-structured)
├── CollisionMesh                  UsdGeom.TetMesh (auto) + PhysxCollisionAPI
├── CableMaterial                  UsdShade.Material (deformable material, bound at root)
├── attachmentStart                Scope + PhysxAutoDeformableAttachmentAPI
└── attachmentEnd                  Scope + PhysxAutoDeformableAttachmentAPI

/World/Start                       Xform + UsdPhysics.RigidBodyAPI (kinematic)
└── shape                          small box collider for visualisation/anchoring

/World/End                         Xform + UsdPhysics.RigidBodyAPI
└── shape                          small box collider for visualisation/anchoring
```
