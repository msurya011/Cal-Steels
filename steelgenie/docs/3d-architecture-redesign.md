# CalSteel 3D Visualization — Architecture & Roadmap

## Status quo (what already exists, as of this redesign)

Before redesigning, it's worth being precise about what's already real vs. what's aspirational, since a lot of the "global building" foundation is already built:

- **Global coordinate system**: implemented in `backend/app/engineering/registration.py`. Every member gets world X/Y/Z in feet — X/Z from grid-line registration between sheets, Y from real Top-of-Steel elevation. Pages are never rendered in page-local space.
- **Floor aggregation**: `cluster_pages_into_floors()` groups any pages sharing a T.O.S. into one floor automatically, regardless of which drawing they came from.
- **Multi-sheet registration**: `register_floor()` aligns sheets of the same floor against each other using real grid-bubble labels (`extract_grid_lines()` in `main.py`), with a correlation-based fallback when labels can't be matched confidently.
- **Solid member rendering**: `buildingSceneStore.ts`'s `_createSolidMesh()` extrudes real AISC cross-section proportions per member type, not generic tubes.
- **Persistent single scene**: one `BuildingSceneStore` singleton per project, incrementally appended as pages extract — never rebuilt from scratch except on scope/color-mode change.
- **Selection sync**: clicking a member in 3D or 2D updates the same `selectedMemberId` in the shared Zustand store; both views react to it.
- **Camera presets**: Top/Front/Back/Left/Right/Home/NE-Iso/NW-Iso, orthographic ⇄ perspective toggle.

This redesign builds *on top of* that foundation rather than replacing it — the pipeline described below already exists end-to-end; what's new is performance (instancing), professional viewer tooling (isolation, clipping, measurement), and the editing/re-sync loop.

## Pipeline (current + target state)

```
PDF
 │
 ▼
Extraction (main.py: vector text + geometry, or raster+OCR fallback)
 │  → per-member fraction coordinates (page-local, 0..1), profile, piecemark, kind
 ▼
Normalization (analyse.py: run_analyse)
 │  → persisted to `members` table, geometry.{x,y,bx1,by1,bx2,by2}
 ▼
Grid Registration (registration.py: extract_grid_lines → register_floor)
 │  → page_registrations: tx_ft, ty_ft, ft_per_pct_x/y per page
 ▼
Coordinate Transformation (registration.py: write_global_geometry)
 │  → geometry.global.{gx_ft, gy_ft, gx1_ft, gy1_ft, gx2_ft, gy2_ft}
 ▼
Floor Assignment (registration.py: cluster_pages_into_floors)
 │  → floors table, page_floor_links, elevation_ft
 ▼
Member Database (members table — single source of truth, DB-agnostic: real Supabase in prod, JSON-file mock locally)
 ▼
Building Aggregator (model.py: get_merged_model, scope=building)
 │  → stacks floors by real elevation_ft, dedupes overlapping members
 ▼
Geometry Generator (buildingSceneStore.ts: addPageMembers / rebuildFull)
 │  → SceneMember records + solid mesh / instanced geometry
 ▼
3D Renderer (Three.js scene, persistent singleton, incremental append)
 ▼
Interaction Layer (StructuralViewer3D.tsx: orbit/pan/zoom, pick, select, legend, viewer tools)
```

Every stage above is already independently callable (e.g. `register_floor(floor_id)` can run standalone), which is what makes "modular" real rather than aspirational — there's no single monolithic "build everything" function.

## What's being added in this pass

### 1. Instanced/batched geometry (performance)
Today each member is its own `THREE.Mesh` (own geometry + material + draw call). Fine at hundreds of members, prohibitive at thousands. Fix: group members by `(kind, roundedWidth, roundedHeight)` into `THREE.InstancedMesh` buckets — one draw call per bucket instead of one per member. Selection highlighting still works per-instance via `setColorAt`. Frustum culling comes largely free from Three.js for standard meshes; for instanced meshes we set a generous `boundingSphere` on the whole batch (safe over-approximation) so large buildings don't get pathologically culled/un-culled per frame.

LOD (level-of-detail) is *not* implemented in this pass — for a structural model where every member's exact profile matters at any zoom, swapping to a simplified proxy at distance saves little and risks looking wrong when a user zooms into a "simplified" beam. Deferred until real-world building sizes prove it's needed.

### 2. Professional viewer controls
- **Type isolation panel**: independent hide/show per member kind (beam/column/brace/joist), decoupled from Color-By mode (today, hiding only works by clicking a legend chip in the active color mode).
- **Transparency / X-ray toggle**: global opacity slider so interior framing is visible through exterior members.
- **Fit to selection / Fit building**: camera actions that frame exactly the selected member(s) or the whole model.
- **Member search**: type a piecemark, jump the camera and selection to it.

### 3. Section/clipping plane
A single horizontal `THREE.Plane` fed into `renderer.clippingPlanes`, with a slider bound to world Y — lets a user "peel back" upper floors to inspect a specific level without hiding whole floors via scope switching.

### 4. Measurement tool
Click two points (snapped to nearest member endpoint via the existing `pickAt`/spatial grid), draw a dimension line + label with real feet-inches distance.

### 5. Editing → re-sync loop
Already partially real (2D plan editing calls the same `members` API the 3D scope=sheet editor uses, and `bumpModelRefresh()` triggers an incremental 3D reload). This pass tightens it: an edit to a member's endpoint in 2D triggers `addPageMembers(pageId, [...], force=true)` for just that page instead of requiring a full building rebuild, and updates `geometry.global` server-side so the 3D position is correct without waiting for a full re-registration pass.

## What's explicitly out of scope for this pass (and why)

- **Full snap-to-node / reconnect-members editing UI**: real feature, but it's a standalone editing-interaction project (drag gizmos, connection validation, undo/redo integration) that deserves its own design pass rather than being bolted onto a rendering-focused redesign.
- **Clash detection**: needs real member solid-geometry intersection tests at building scale — a correctness-critical feature that shouldn't be rushed alongside a rendering rewrite.
- **BOM/Fabrication/Connections/Plates modules**: already have their own tabs (Columns, Braces, BOM) with real data flows; this redesign doesn't touch them.

## Milestones

1. **M1 — Instancing** — batch geometry generation, verify existing selection/color/legend features still work against instanced meshes. *(this session)*
2. **M2 — Viewer tooling** — type isolation, transparency, fit actions, search. *(this session)*
3. **M3 — Section/clip + measurement** — the two most-requested structural-review tools. *(this session)*
4. **M4 — Tighter edit/re-sync loop** — per-page incremental re-geometry on 2D edits instead of full rebuild. *(this session, as time allows)*
5. **M5 — Snap/reconnect editing** — deferred, own design pass.
6. **M6 — Clash detection** — deferred, own design pass.
