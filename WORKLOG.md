# Cable Stretch Monitor — Arbeitsstand & Lessons Learned

> Stand: 2026-06-29. Diese Notiz hält fest, **was versucht wurde**, **was
> funktioniert hat**, **was die echten Ursachen waren** und **wo wir uns
> verrannt haben**. Der Code wurde zwischenzeitlich auf den Ursprungszustand
> zurückgesetzt (`git status` sauber) — dieses Dokument ist die Gedächtnis-
> stütze, damit der Neuanfang die Erkenntnisse nicht verliert.

---

## Ziel (unverändert)

Ein **Abbruchkriterium** für die Kabelsimulation:

1. Dehnung des Kabels zur Laufzeit **monitoren**.
2. Bei Überschreiten eines Schwellwerts → **Signal** ausgeben
   (Debug-Konsequenz: Material wird rot).
3. Bei Unterschreiten eines zweiten Schwellwerts → Signal aus, **alte Farbe
   wiederherstellen** (Hysterese, kein Latch).

Spätere Bausteine (noch offen): GUI zum Scharfstellen + externe Python-API.

### Abgestimmte Entscheidungen

- **Lokal pro Tetraeder** messen: max. Hauptdehnung via Deformationsgradient
  `F = Ds · inv(Dm)`, größter Singulärwert (SVD). Nicht global.
- Schwellwert **relativ zu einer eingeschwungenen Baseline** — das Kabel sackt
  beim Start unter Gravitation, erst danach ist „100 %". Baseline per
  **Auto-Stabilisierung** (warten, bis sich die Dehnung kaum noch ändert).
- Default **+2 %**: trigger `1.02`, release `1.005`.
- GUI: „Cable Creation" als Foldable, darunter „Cable Monitoring" als Foldable
  mit **Arm/Disarm** + Live-Status.
- Engine bleibt **PhysX** (nicht Newton).

---

## Ausgangspunkt: das funktionierende Skript

`scripts/cable_stretch_to_red.py` (von Codex) war ein **guter, schlanker
Ansatz** und lief korrekt gegen eine **handgemachte** `cable.usd`:

- erstellt **selbst** eine Tensor-`simulation_view` (`create_simulation_view`)
- liest `get_simulation_nodal_positions()`
- rechnet pro Tet die Hauptdehnung (SVD)
- färbt einen **fest verdrahteten** Shader rot, **latcht** (geht nie zurück)
- Pfade hartcodiert: `/World/cable/Cable`, `/World/Looks/Cable_vis/Shader`

**Warum es lief:** Die handgemachte `cable.usd` hat eine PhysicsScene mit
`PhysxSceneAPI` → **GPU-Dynamics an** → nodale Positionen lesbar.

Aufruf des Nutzers:
`exec(open(".../scripts/cable_stretch_to_red.py").read())` im Script Editor.

---

## Root-Cause-Findings (chronologisch)

### Befund A — Extension lädt & baut, aber Physik-Parameter wirkten nicht
Log-Warnung dutzendfach:
`physxDeformableBody:* is authored, but a PhysxSurfaceDeformableBodyAPI is not
applied. Simulation will default to a fallback value.`
→ kosmetisch beim Property-Widget, aber Hinweis auf möglichen API-Mismatch
(Volume- vs. Surface-Deformable). **Noch nicht abschließend geklärt** —
Verdacht: könnte mit „Kabel dehnt sich beim Start von selbst" zusammenhängen.

### Befund B — `stage_id` fehlte bei der Tensor-View
`Failed to create simulation view with backend 'physx'` /
`Failed to get a valid attached USD stage id`.
Ursache: `create_simulation_view(frontend)` **ohne `stage_id`**.
Lösung: `stage_id = omni.usd.get_context().get_stage_id()` mitgeben.
Kanonisches Muster aus `SimulationManager` (Isaac):
```python
stage_id = omni.usd.get_context().get_stage_id()
sim_view = omni.physics.tensors.create_simulation_view("warp", stage_id=stage_id)
sim_view.set_subspace_roots("/")
```

### Befund C — PhysX lief auf der **CPU** (Schlüssel-Erkenntnis)
`CpuSimulationView::getSimulationNodalPositions is not implemented yet`.

**Wichtig — verbreitetes Missverständnis:** Isaac **rendert** immer auf GPU,
aber **PhysX rechnet nicht automatisch auf GPU**. Die GPU-Dynamics-Pipeline ist
eine Eigenschaft der **PhysicsScene** (`physxScene:enableGPUDynamics`,
Schema-Default `true`) — **gilt aber nur, wenn die Scene `PhysxSceneAPI` hat**.

- Extension baut eine **nackte `UsdPhysics.Scene`** (ohne `PhysxSceneAPI`)
  → kein GPU-Default → **CPU** → nodale Positionen nicht lesbar.
- Handgemachte `cable.usd` hat `apiSchemas = ["NewtonSceneAPI", "PhysxSceneAPI"]`
  → GPU → lief.

**Fix-Ansatz** (in `usd_utils.py`):
```python
from pxr import PhysxSchema
physx_scene = PhysxSchema.PhysxSceneAPI.Apply(scene_prim)
physx_scene.CreateEnableGPUDynamicsAttr(True)
physx_scene.CreateBroadphaseTypeAttr("GPU")   # allowedTokens: GPU, MBP, SAP
```
Im Test bestätigt: Log zeigte danach „Enabled GPU dynamics" und der CPU-Fehler
war weg. **Dieser Fix ist korrekt und sollte erhalten bleiben.**

### Befund D — OFFEN: View liefert trotz GPU keine Positionen
Nach GPU-Fix neuer Fehler:
`Failed to get deformable body simulation mesh nodal positions from backend`
(`omni/physics/tensors/api.py:4364`), ausgelöst aus `_measure_max_stretch`.

**Wahrscheinliche Ursache:** Im Refactor wurde
`SimulationManager.get_physics_simulation_view()` **bevorzugt**. Diese geteilte
View passt offenbar **nicht** zu diesem Deformable-Body (liefert keine
Positionen), während der **Skript-Weg (eigene `create_simulation_view`)
funktioniert hat**. → Das ist die heißeste Stelle für den Fix.

---

## Ehrliche Einordnung: wo wir uns verrannt haben

- Das Originalskript war in der **Kern-Mechanik schlank und korrekt** (eigene
  View, Positionen lesen, SVD).
- Im Refactor kamen **Robustheits-Schichten** dazu, die das Skript nie brauchte:
  - **SimulationManager-View bevorzugen** → bricht die Messung (Befund D).
  - **Retry-Init (120 Versuche)** → kaschiert Symptome statt Ursachen.
- Diese Schichten haben **mehr Probleme erzeugt als gelöst**. Lehre:
  **so nah wie möglich am bewährten Skript bleiben.**

**Zu Recht da (behalten):** GPU-Scene-Fix (C), `stage_id` (B), Hysterese,
Auto-Baseline, GUI, dynamische Shader-Suche über `material:binding`.

---

## Empfohlener Neuanfang (vereinbart: VEREINFACHEN)

Beim Wiederaufbau der Monitor-Logik:

1. **View-Erstellung exakt wie das Skript**: eigene
   `create_simulation_view(frontend, stage_id=<aktive stage id>)` —
   plus der einzig nötige Zusatz `stage_id` (Befund B).
   **Kein** `SimulationManager`-View-Vorzug.
2. **Keine Retry-Akrobatik** — höchstens „init beim ersten Step, sonst Fehler".
3. **Hysterese** statt Latch (trigger/release).
4. **Auto-Baseline** (eingeschwungener Zustand = 100 %).
5. **GPU-Scene-Fix** beim Scene-Erstellen mitnehmen (Befund C).
6. **Shader dynamisch** über `material:binding` finden, nicht hartcodieren.
7. GUI: Creation-Foldable + Monitoring-Foldable (Arm/Disarm/Status) +
   Button „Fix Physics Scene (GPU)" für bestehende Szenen.

---

## Verifizierte technische Fakten (aus Quellen geprüft)

- `omni.physics.tensors.create_simulation_view(frontend_name, stage_id=-1,
  backend="physx")` — erstes Arg ist das **Frontend** (`numpy|torch|warp|tf`).
- `SimulationView.set_subspace_roots("/")` und
  `.create_volume_deformable_body_view(path)` existieren.
- `body_view.get_simulation_nodal_positions()` → Shape `(count, nodes, 3)`;
  nur im **GPU**-View implementiert.
- `physxScene:enableGPUDynamics` Schema-Default = `1` (true), **aber nur mit
  `PhysxSceneAPI`**.
- `PhysxSchema.PhysxSceneAPI`: `CreateEnableGPUDynamicsAttr`,
  `CreateBroadphaseTypeAttr` (Tokens: `GPU`, `MBP`, `SAP`).
- Aktive Engine im Test war **PhysX** (Log:
  `VariantSwitcher: Active simulation detected: 'PhysX'`).

---

## Referenz-Hierarchie (aus funktionierender `cable.usd`)

```
/World/PhysicsScene        apiSchemas: NewtonSceneAPI, PhysxSceneAPI   ← GPU!
/World/Cable               Xform  (Deformable, material:binding → Looks/PreviewSurface)
  ├── cooking_mesh         Mesh
  ├── simulation_mesh      TetMesh (OmniPhysicsVolumeDeformableSimAPI)
  ├── collision_mesh       TetMesh (PhysicsCollisionAPI, PhysxCollisionAPI)
  ├── Cable                Material (OmniPhysicsDeformableMaterialAPI)  ← Physik
  ├── attachmentStart      Scope (PhysxAutoDeformableAttachmentAPI)
  └── attachmentEnd        Scope
/World/Looks/PreviewSurface  Material → Shader (UsdPreviewSurface)      ← visuell (rot)
/World/Start, /World/End   Xform (RigidBodyAPI) + Cube
```

Gewünschte gruppierte Variante (Booleans `create_material`, `group_cable`,
noch nicht gebaut): alles unter `/World/Cable/…`, also `/World/Cable/Cable`,
`/World/Cable/Looks`, `/World/Cable/Start`, `/World/Cable/End`.

---

## Test-Rezept (für bestehendes Kabel)

1. Extension neu laden.
2. Timeline **Stop**.
3. Monitoring → **„Fix Physics Scene (enable GPU dynamics)"**.
4. **Play** → **Arm Monitor**.
5. Status sollte `Warmup...` → `[ok] relative=…` zeigen; bei > +2 % → rot,
   danach wieder Originalfarbe.

---

## Backlog / offene Punkte

- [ ] **D fixen**: Monitor-View auf Skript-Weg (eigene `create_simulation_view`
      + `stage_id`), SimulationManager-Vorzug + Retry raus.
- [ ] **GPU-Scene-Fix** wieder einbauen (`usd_utils.py`, Befund C).
- [ ] **Befund A** prüfen: Surface- vs. Volume-Deformable-API als Ursache für
      „Kabel dehnt sich beim Start von selbst"?
- [ ] **B-Anforderung**: Booleans `create_material` + `group_cable` (gruppierte
      Hierarchie + visuelles PreviewSurface-Material).
- [ ] **D-Anforderung**: externe Python-API zum Scharfstellen des Kriteriums.

---

## Relevante Pfade

- Extension: `A:\isaac-sim-exts\omni.cable.sim`
- Referenz-Prototyp: `scripts/cable_stretch_to_red.py` (lief korrekt)
- Funktionierende USD: `A:\OneDrive - Wandelbots GmbH\nvidia_omniverse\projects\Vitus\projekte_sidequests\cable\cable.usd`
- USD-Tools: `A:\Tools\OpenUSD\25.08.71e038c1\bin` (`usdcat`, `usdtree`)
- Isaac-Logs: `C:\Users\Vitus\.nvidia-omniverse\logs\Kit\Isaac-Sim Full\6.0`
