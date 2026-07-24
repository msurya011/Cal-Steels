# Multi-Sheet Structural Extraction & Unified 3D Model — Architecture

Status: proposal · Author: Claude (CalSteel co-dev session) · Date: 2026-07-10

## 1. Problem statement

SteelGenie ingests multi-sheet PDF sets where several plan sheets describe the
same physical floor (e.g. "Partial Level 04 Framing Plan — Zone A" and "...
Zone B", pages 31–33 in the reference project) and merges them into one
contiguous, shared-coordinate 3D model of the building. CalSteel currently
does not do this.

Grounded in the current codebase (`backend/`, `frontend/`), here is the exact
gap:

| Capability | CalSteel today | SteelGenie (observed) |
|---|---|---|
| Coordinate system | Each page has its own **percentage-of-image** local space (`members.geometry.{x,y,w,h,...}`, no `viewBox`, no real-world units) | Shared project-global coordinate system in feet |
| Floor concept | Implicit: `pages` table, one row per PDF page, `tos_ft` used as a sort key | `floors`/levels are first-class; **one floor can span multiple sheets** |
| Grid lines | `v_grid`/`h_grid` computed **ephemerally per request** inside `main.py` for snap-to-grid only, never persisted, never labeled ("1","2","A","B") | Grid bubbles are extracted, labeled, and used as the registration key across sheets |
| Multi-sheet stitching | None — `3d/page.tsx.loadModel()` fetches each *built page* independently and stacks them along Z in `tos_ft` order | Zone A + Zone B sheets of the same level are laterally (X/Y) merged into one footprint before stacking |
| Match-lines | Not extracted | Sheets carry "MATCH TO: 1/S134 A/B" call-outs, a strong registration signal |
| BOM summary scope | One flat BOM table, `sheet`/`drawing_id` filter exists but no rollup panel | Project Summary vs Sheet Summary counts (Column/Beam/VBrace/HBrace/Joists/Moment Connection/Bolt/Embed Plate/Camber/Anchor/Weld Studs/Total Weight/Hrs-per-Ton) |
| 3D fetch pattern | N sequential `modelApi.get()` calls, one per built page, client-side merge | Single merged model per scope |

Everything below is designed to close this gap without discarding the
existing per-page CV pipeline (`backend/main.py`, `app/workers/analyse.py`) —
that pipeline still does per-sheet extraction; this proposal adds a
**registration layer on top of it**.

## 2. Assumptions (stated explicitly, per the ambiguity in the source screenshots)

1. **Grid bubbles are the primary registration key.** Two sheets belong to
   the same floor and are laterally adjacent if they share ≥2 labeled grid
   lines (e.g. both contain vertical grid "3" and horizontal grid "C") whose
   relative spacing is consistent once shape/scale is accounted for.
2. **Match-line call-outs are a secondary, higher-confidence signal** when
   present (`MATCH TO: 1/S134 A`), but cannot be assumed to exist on every
   sheet set — the algorithm must work from grids alone.
3. **Scale is per-page but usually uniform within a level** (`scale_num`,
   e.g. `3/16" = 1'-0"`) — registration solves for translation + rotation
   only, not independent scale per sheet, unless grid spacing disagrees by
   more than a tolerance (flag for manual review rather than guess).
4. **A "floor" is a logical grouping of one or more pages**, not a single
   page. Existing `tos_ft` becomes a floor-level property, not a page-level
   one.
5. Registration is **heuristic and will not be 100% automatic** on real
   drawing sets — the design includes a confidence score and a manual
   nudge/rotate override, mirroring the existing `need_review` status
   pattern already used for member confidence.

## 3. Data model

New tables (migration `007_multi_sheet_model.sql`), additive only — no
existing table is dropped or renamed.

```sql
-- A floor/level groups one or more pages into one structural story.
CREATE TABLE floors (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id    UUID REFERENCES projects ON DELETE CASCADE NOT NULL,
  name          TEXT NOT NULL,              -- "Level 04", "Third Floor"
  elevation_ft  FLOAT,                      -- top-of-steel, moved off `pages.tos_ft`
  sort_order    INT NOT NULL DEFAULT 0,
  status        TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft','registered','need_review')),
  created_at    TIMESTAMPTZ DEFAULT now(),
  updated_at    TIMESTAMPTZ DEFAULT now()
);

-- Which pages belong to which floor, plus a human label for the zone.
CREATE TABLE page_floor_links (
  page_id     UUID REFERENCES pages ON DELETE CASCADE NOT NULL,
  floor_id    UUID REFERENCES floors ON DELETE CASCADE NOT NULL,
  zone_label  TEXT,                         -- "Zone A", "Zone B"
  PRIMARY KEY (page_id)                     -- a page belongs to exactly one floor
);

-- Extracted/labeled grid lines, in page-local percentage space (same
-- convention as members.geometry) until registration resolves a transform.
CREATE TABLE grids (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  page_id     UUID REFERENCES pages ON DELETE CASCADE NOT NULL,
  axis        TEXT NOT NULL CHECK (axis IN ('x','y')),
  label       TEXT NOT NULL,                -- "1", "2", "A", "B"
  position    FLOAT NOT NULL,               -- percentage-of-page coordinate
  confidence  FLOAT,
  source      TEXT NOT NULL DEFAULT 'ai' CHECK (source IN ('ai','manual')),
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- Match-line call-outs OCR'd off the sheet border ("MATCH TO: 1/S134 B").
CREATE TABLE match_lines (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  page_id           UUID REFERENCES pages ON DELETE CASCADE NOT NULL,
  edge              TEXT NOT NULL CHECK (edge IN ('top','bottom','left','right')),
  raw_text          TEXT,
  target_sheet_no   TEXT,                   -- parsed "S134"
  target_zone_label TEXT,                   -- parsed "B"
  confidence        FLOAT,
  created_at        TIMESTAMPTZ DEFAULT now()
);

-- Resolved per-page transform into floor-global feet coordinates.
CREATE TABLE page_registrations (
  page_id      UUID PRIMARY KEY REFERENCES pages ON DELETE CASCADE,
  floor_id     UUID REFERENCES floors ON DELETE CASCADE NOT NULL,
  tx_ft        FLOAT NOT NULL DEFAULT 0,
  ty_ft        FLOAT NOT NULL DEFAULT 0,
  rotation_deg FLOAT NOT NULL DEFAULT 0,
  ft_per_pct_x FLOAT NOT NULL,               -- derived from scale_num + page image size
  ft_per_pct_y FLOAT NOT NULL,
  anchor       BOOLEAN NOT NULL DEFAULT false, -- true for the reference page of the floor
  confidence   FLOAT,
  method       TEXT CHECK (method IN ('grid_match','match_line','manual','identity')),
  created_at   TIMESTAMPTZ DEFAULT now(),
  updated_at   TIMESTAMPTZ DEFAULT now()
);
```

Additive change to `pages`: `level_name TEXT`, `zone_label TEXT` (raw OCR/
title-block guess, pre-clustering — `page_floor_links.zone_label` is the
confirmed value after review).

Additive change to `members.geometry` (still the same JSONB column, no
schema migration needed — just new optional keys written by the build
pipeline once a page is registered):

```json
{
  "x": 41.2, "y": 12.8, "w": 0, "h": 0,          // existing page-local %
  "global": { "gx1_ft": 118.4, "gy1_ft": 42.0,    // NEW — floor-global feet
              "gx2_ft": 150.9, "gy2_ft": 42.0,
              "floor_id": "…" }
}
```

Keeping `global` inside the existing JSONB avoids a breaking schema change
and keeps page-local rendering (the 2D overlay work already done this
session) completely unaffected.

## 4. Extraction & registration pipeline

```mermaid
flowchart TD
    A[PDF upload] --> B[ingest job\nrasterize pages]
    B --> C[analyse job\nper-page CV extraction\n(existing: beams/columns/braces/joists)]
    C --> C2[NEW: grid line + grid-bubble OCR\n→ grids table]
    C --> C3[NEW: match-line OCR\n→ match_lines table]
    C2 --> D[NEW: floor clustering\ntitle-block level_name + zone_label\n→ floors, page_floor_links]
    C3 --> D
    D --> E[NEW: registration engine\nper floor: solve page transforms]
    E --> F[page_registrations\n(tx, ty, rotation, confidence)]
    F --> G[NEW: global geometry pass\nwrite members.geometry.global]
    G --> H[build job\n(existing engineering/build.py)\n+ seam dedup]
    H --> I[bom_items]
    G --> J[NEW /model endpoint\nscope=building|floor|sheet]
    J --> K[3D viewer]
    I --> L[Properties panel\nProject Summary / Sheet Summary]
```

Existing stages (`ingest`, `analyse`, `build`) are unchanged in their current
responsibilities; the new stages are additive jobs/sub-stages that consume
their output.

## 5. Registration algorithm (detail for stage E)

Input: all pages assigned to one `floor_id` (from stage D), each with its
`grids` rows and `match_lines` rows.

1. **Build a registration graph.** Nodes = pages. For every pair of pages
   `(p, q)` in the floor, compute an edge if they share ≥2 labeled grid
   lines on the same axis with consistent spacing (within tolerance —
   default 3% of bay width), or if a `match_line` on `p` names `q`'s
   `sheet_no`/`zone_label`. Edge weight = confidence (grid-match count,
   or fixed high weight for an explicit match-line).
2. **Pick an anchor.** The page with the most members (or lowest `idx`) in
   the floor becomes `anchor = true`, `tx=ty=rotation=0`.
3. **Propagate transforms.** Walk the maximum-spanning-tree of the
   registration graph from the anchor outward (Phase 3 scope: spanning
   tree propagation is sufficient and O(n)). For each edge `(p→q)`, solve
   the 2D similarity transform (translation + rotation, scale fixed from
   `scale_num`) that best aligns `q`'s matched grid coordinates onto `p`'s
   already-resolved global coordinates (least-squares over matched grid
   pairs). Compose with `p`'s already-known transform to get `q`'s.
   *(Future hardening, not v1: replace spanning-tree propagation with a
   global least-squares bundle adjustment over all edges at once, so
   registration error doesn't accumulate/drift across a long chain of
   sheets — flagged in §8 Phase 7.)*
4. **Disconnected pages** (no shared grids or match-lines found with any
   other page in the floor) get `method='identity'`, `confidence=0`, and the
   floor is marked `status='need_review'`. They still render (at a default
   offset) rather than being dropped, consistent with the existing pattern
   of surfacing low-confidence output instead of hiding it.
5. **Persist** to `page_registrations`. Never silently overwrite a row with
   `method='manual'` — manual corrections win and are excluded from
   re-registration on subsequent re-analyse runs.

## 6. Global geometry & seam deduplication (stage G/H)

For every member on a registered page, apply that page's transform to
`geometry.{x,y,bx1,by1,bx2,by2}` (percentage → feet) and write the result
into `geometry.global`. This is a pure function of already-known values, so
it can run as a cheap post-pass after `page_registrations` changes, without
re-running CV extraction.

**Seam dedup**, needed because two adjacent sheets typically both draw a few
feet of overlap along their shared edge: after computing global coordinates,
group members by `(floor_id, kind, section, rounded(gx), rounded(gy),
rounded(angle))` within a small tolerance (e.g. 6 inches, half a foot). If
two members from *different pages* collide, keep the one with higher
`confidence`/`status='verified'` and mark the other `status='excluded'` so
it drops out of BOM counts but stays visible for audit (existing `excluded`
status already exists on `members.status` — no schema change needed here).

## 7. Visualization & 2D↔3D sync spec

**New endpoint** `GET /projects/{id}/model?scope=building|floor|sheet&scope_id=...`
returns pre-merged, deduped `global` geometry for the requested scope in one
call, replacing `3d/page.tsx`'s current per-page loop (`drawingsApi.list` →
`listPages` → N × `modelApi.get`).

**Scope dropdown** (replaces implicit "all built pages" behavior):
- `Building` — every floor, full project, stacked by `floors.sort_order`.
- a specific floor — all its pages merged laterally, single Z-level.
- a specific sheet/page — for isolating one zone during review.

**Color mode dropdown** — keep existing `member_type` vs `building` toggle
(`TYPE_COLOR` map in `3d/page.tsx`), unchanged.

**Selection sync** — each `ModelMember` already carries a synthetic id
`${pageId}_${memberId}`; on click, resolve `pageId` → `drawing_id` and route/
scroll the 2D Plans view to that page + highlight the member (the overlay
components already support a "highlighted member" concept from this
session's Properties-panel work — reuse it rather than building a new
highlight path).

**Hover tooltip**, matching the observed format exactly:
`{piecemark} | {section} | {length_ft as ft-in-fraction} | {weight_lbs} lbs | {status label} | Labor: {labor_code}`
— all fields are already computed by `app/engineering/build.py`; the 3D
endpoint should join against the latest `bom_items` row for each member
(by piecemark) rather than recomputing weight/labor client-side.

## 8. Properties panel — Project Summary / Sheet Summary

Both blocks render the same field set:
Column · Beam · Vertical Brace · Horizontal Brace · Joists · Moment
Connection · Bolt · Embed Plate · Camber · Anchor · Weld Studs · Total
Weight (tons) · Hrs/Ton.

Implementation: add a `summarize(scope: 'project'|'page', scope_id)` helper
in `app/engineering/build.py` that reuses the existing `run_build()`
aggregation logic (it already computes weight, and `bom_items` already has
`camber`, `cope`, `holes`, `weld_studs`, `category`) rather than writing a
second parallel aggregation path. "Moment Connection" and "Bolt"/"Embed
Plate"/"Anchor" counts come from `members.kind`/`geometry.connections`
(added earlier this session for the Connections accordion) and
`column_groups.anchors`/`base_plate` respectively — both already persisted,
just need counting, not new extraction.

Frontend: two collapsible sections in `PropertiesPanel.tsx` (or a new
`ModelSummaryPanel.tsx` used only on the 3D page), `Project Summary` always
scoped to the whole project, `Sheet Summary` scoped to whatever page is
currently active/selected in the 3D scope dropdown.

## 9. Performance

- **One HTTP call, not N.** The new `/model` endpoint returns the whole
  requested scope pre-merged server-side; `3d/page.tsx.loadModel()`'s
  current per-page loop is deleted.
- **Registration runs once per floor edit, cached.** `page_registrations`
  is only recomputed when a page in that floor is re-analysed or a grid is
  manually edited — not on every 3D page load.
- **Batched Three.js geometry.** Current code creates one `THREE.Mesh` per
  member (`sceneObjectsRef.current: THREE.Mesh[]`); at 287+ members per
  floor (observed in the reference project) this is the first thing to fix.
  Group members by `(kind, color)` and merge into one `BufferGeometry` per
  group via `THREE.BufferGeometryUtils.mergeGeometries`, so a floor renders
  as a handful of draw calls instead of hundreds.
- **LOD for `Building` scope.** When scope is the whole building and floor
  count is high, render non-active floors as simplified/thinner wireframe
  and only the selected floor at full fidelity + labels.
- **Seam dedup and global-coordinate writes run as an incremental pass**,
  not a full recompute, keyed off `page_registrations.updated_at` vs
  `members.updated_at`.

## 10. Phased implementation roadmap

| Phase | Scope | Key files/additions | User-visible? |
|---|---|---|---|
| 0 | Schema foundation | `infra/supabase/migrations/007_multi_sheet_model.sql` (tables in §3); mock `MockClient` local_db support | No |
| 1 | Level/zone clustering | `pages.level_name/zone_label` extraction (regex on `title`/`sheet_no` OCR); auto-cluster into `floors`/`page_floor_links`; manual override UI in page settings | Minor — floor grouping visible in a new "Floors" list |
| 2 | Grid persistence | Persist existing ephemeral `v_grid`/`h_grid` (already computed in `main.py`) + OCR bubble labels into `grids` table, scoped per page | No (internal) |
| 3 | Registration engine | New job stage implementing §5 (graph build, spanning-tree propagation, confidence); `page_registrations` writes; manual nudge/rotate override UI | Yes — floor status badge (registered/need review) |
| 4 | Global geometry + seam dedup | §6: `members.geometry.global` write pass; dedup marking `status='excluded'` at seams | Indirect — BOM counts become accurate for multi-sheet floors |
| 5 | `/model` endpoint + 3D viewer rework | §7: new endpoint; rewrite `3d/page.tsx.loadModel()` to single call; scope dropdown (Building/Floor/Sheet); batched Three.js rendering (§9); click-to-sync with 2D | Yes — main deliverable |
| 6 | Summary panel | §8: `summarize()` helper + Project/Sheet Summary UI | Yes |
| 7 | Hardening | Match-line OCR to raise registration confidence; replace spanning-tree propagation with global least-squares bundle adjustment; LOD tuning; large-project (100+ floor) perf pass | Yes, quality/robustness only |

Phases 0–2 are prerequisites and carry no visible change, so they're safe to
ship incrementally without disrupting the current single-sheet workflow —
projects with only one page per floor simply get `floor = page` 1:1 with an
identity transform, and everything built this session (2D overlay markers,
Connections accordion, Columns/Braces pages, Config page, BOM) continues to
work unmodified throughout.

## 11. Explicit non-goals (scope guard)

- Not building a general CAD/IFC geometry kernel — registration solves a 2D
  similarity transform per sheet, not full 3D solid modeling.
- Not attempting perfect fully-automatic registration — confidence scoring
  and manual override are part of the design, not a fallback bolted on
  later.
- Not touching the existing per-sheet CV extraction pipeline's detection
  logic (beam/column/brace classification) — this proposal only adds a
  layer on top that stitches its *output* across sheets.
