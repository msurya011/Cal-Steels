# Column Extraction & Visualization — Technical Plan
**Product:** CalSteel takeoff workspace · **Date:** 2026-07-09
**Basis:** observed SteelGenie v1.5.1 behavior (columns rendered as oriented steel symbols at grid intersections, green selection nodes, per-member rotation & status editing, Column tool "C", column groups feeding a Column Scheduler) and the current CalSteel code (backend `detect_column_symbols()` in the legacy engine; frontend `OverlayLayer`, layers slice, selection model, `column` draw tool). Where SteelGenie internals are not observable, the design follows structural-drafting conventions and is marked **[A]**.

---

## 1. Current implementation vs. target

| Stage | CalSteel today | Target (SteelGenie-grade) |
|---|---|---|
| Detection | `detect_column_symbols()` finds I/H glyphs in vector paths; matched greedily to profile labels; skipped for raster pages | Keep as Layer 1; add grid-intersection & beam-endpoint validation, raster template fallback, orientation extraction |
| Center position | Symbol bbox center, fraction-of-page | Sub-symbol precision: centroid of flange strokes; snap to nearest grid intersection within tolerance, retain `snap_offset` |
| Orientation | `rotation` field exists; UI edits it numerically | Auto-detect web direction (0°/90°, ±45° for skewed **[A]**); render symbol rotated; drag-rotate handle |
| Rendering | Green square node + label | True steel symbol (I-glyph for W, box for HSS, pipe circle), scaled to section depth × page scale, with state styles |
| States | selected only | normal · hover · selected · verified · need_review · error(no-grid/no-label) · missing(suggested) |
| Editing | Click-place (C tool), properties panel | + drag-to-move w/ grid snap, rotate handle, validation overlay, "suggest missing columns" |
| Integration | Members table, Explorer, BOM, 3D share `kind='column'` | unchanged — all enhancements flow through existing member schema |

## 2. Detection & placement pipeline (backend)

**Layer 1 — Vector symbol scan (existing, keep).** I/H glyph candidates from `page.get_drawings()` strokes; emit `{bbox, strokes}`.

**Layer 2 — Orientation & center refinement (new).**
```python
def refine_column(candidate):
    flanges = parallel_stroke_pairs(candidate.strokes)          # 2 long parallels
    web     = perpendicular_connector(flanges)                   # 1 connector
    center  = midpoint(web) if web else bbox_center(candidate)
    theta   = angle_of(web) if web else dominant_angle(flanges) + 90
    rotation = quantize(theta, [0, 45, 90, 135])                 # drafting convention
    return center, rotation, confidence_from_geometry(flanges, web)
```

**Layer 3 — Cross-validation (new).** Score each candidate against independent signals; combine into confidence:
```python
score = 0.40 * has_label_match          # profile callout within r=20pt, unclaimed
      + 0.30 * near_grid_intersection   # dist(center, nearest_grid_x ∩ grid_y) < snap_tol
      + 0.20 * beam_endpoint_support    # ≥2 detected beam ends terminate within tol
      + 0.10 * symbol_geometry_quality
status = 'active' if score >= .75 else 'need_review'
error_flags = []                        # 'no_grid', 'no_label', 'orphan' → error state in UI
```
Grid intersections come from the existing `extract_grid_lines()`; beam endpoints from beam span lines already produced by the engine — no new detectors, only a join.

**Layer 4 — Missing-column suggestion (improvement).** At every grid intersection inside the plan boundary where ≥2 beams terminate but no column matched: emit a *ghost* candidate `{kind:'column', source:'suggested', status:'need_review', section:null}`. Estimators confirm (assign section) or dismiss — this converts SteelGenie's silent misses into a review queue. **[A]**

**Layer 5 — Raster fallback (new, flagged).** For scanned sheets: multi-scale template match (rotated I-glyph kernels) + Hough grid intersections; confidence capped at 0.6 so everything lands in review.

**Snapping rule:** if `dist(center, grid_pt) < snap_tol (≈ 6" real-world via scale_ratio)` → store `geometry.x/y = grid_pt`, keep `geometry.raw_x/raw_y` and `snap_offset` for audit; else store raw center with `error_flags:['no_grid']`.

## 3. Data model & API changes

`members` table already carries `kind, section, rotation, status, source, confidence, geometry jsonb`. Extend **geometry payload only** (no migration):
```json
{ "x":0.4312,"y":0.2251, "raw_x":0.4309,"raw_y":0.2249, "snap_offset_ft":0.3,
  "grid_ref":"C-4", "symbol":"I|BOX|PIPE", "depth_in":12.2, "error_flags":[] }
```
- `PATCH /members/{id}` — already accepts geometry/rotation; used by drag-move & rotate.
- `POST /pages/{id}/analyse` — response summary gains `columns:{detected,suggested,errors}`.
- NEW `POST /pages/{id}/columns/validate` → re-runs Layer-3 scoring after manual edits (cheap; reads members + cached grid lines). Single-table queries only (mock-DB constraint).
- `grid_ref` enables the future Column Scheduler grouping (M4) without re-detection.

## 4. Rendering strategy (frontend)

SVG in the existing `OverlayLayer` (canvas count for columns is low — tens, not thousands; SVG keeps crisp zoom + easy hit-testing). One memoized component:

```tsx
function ColumnSymbol({ m, state, scalePxPerFt }: Props) {
  const d = (m.geometry.depth_in ?? 10) / 12 * scalePxPerFt      // symbol size from section depth
  const s = Math.max(10, Math.min(28, d))                        // clamp for readability
  return (
    <g transform={`translate(${x},${y}) rotate(${m.rotation})`}
       className={`col col--${state}`}>
      {m.geometry.symbol === 'BOX'  ? <rect x={-s/2} y={-s/2} width={s} height={s}/> :
       m.geometry.symbol === 'PIPE' ? <circle r={s/2}/> :
       <path d={iGlyphPath(s)} /> /* two flanges + web */}
      {state==='selected' && <RotateHandle r={s/2+8}/>}
      {m.geometry.error_flags?.length > 0 && <ErrorBadge/>}
      {m.source==='suggested' && <circle r={s/2+4} className="ghost-ring"/>}
    </g>
  )
}
```
**State styles** (colors flow from the layers slice / color-mode selector so Layer Filter + Color By stay authoritative):
normal `stroke #16A34A 1.5px` · hover `+glow, cursor grab` · selected `accent #3B82F6 2px + rotate handle` · verified `#10B981 filled flanges` · need_review `#F59E0B dashed` · error `#EF4444 dashed + ⚠ badge (tooltip lists flags)` · missing/suggested `grey ghost ring, 50% opacity, pulsing`.

**Interactions:** drag = pointer-capture move with live grid-snap (magnet within snap_tol; `Alt` disables snap); drop → `PATCH geometry` optimistic; rotate handle drags in 45° detents (`Shift` = free) → `PATCH rotation`; double-click = zoom-to (existing); right-click = context menu (Verify, Set section, Rotate 90°, Dismiss suggestion, Delete). A **validation overlay** toggle (Layer Filter "aids" section) draws snap vectors (raw→snapped) and flags, so QA can see *why* each column sits where it does.

Component wiring (all existing systems untouched at their interfaces): Explorer rows/ properties panel read the same member; BOM Grid counts columns via `kind`; 3D already extrudes columns from `geometry + tos_ft`; suggested ghosts are excluded from BOM/3D until confirmed (`section != null`).

## 5. Missing features vs. SteelGenie (gap list)

1. Oriented steel-symbol rendering (I/box/pipe) — currently generic nodes. *(this plan §4)*
2. Orientation auto-detection + rotate handle. *(§2 L2, §4)*
3. Grid-intersection snapping & `grid_ref` assignment. *(§2 L3)*
4. Beam-endpoint corroboration and error flags. *(§2 L3)*
5. Column validation states incl. error/missing visuals. *(§4)*
6. Raster-page column detection (SteelGenie skips? unknown **[A]** — ours is additive). *(§2 L5)*
7. Missing-column suggestions (beyond SteelGenie). *(§2 L4)*
8. Drag-to-adjust with snap + audit trail (`raw_*`, `snap_offset_ft`). *(§4)*
9. Column Scheduler feed (`grid_ref`, groups) — M4 dependency, enabled by this plan.

## 6. Performance & usability recommendations

- Memoize `ColumnSymbol` on `(geometry hash, rotation, state)`; symbols are few — target <1 ms repaint on state change.
- Run Layers 2–4 inside the existing analyse job (adds ~100–300 ms/sheet; grid + beams already computed). Re-validation endpoint must stay <200 ms so drag-drop feels instant.
- Add eval-harness metrics: `column_recall`, `false_columns`, `orientation_acc`, `snap_rate` per corpus sheet; CI-gate like beams.
- Usability: after Extract, auto-open the Explorer filtered to `column + need_review`; keyboard `R` rotates selected column 90°; suggestion ghosts get a one-key confirm (Enter) with a section picker pre-filtered to column shapes (W, HSS).

## 7. Delivery order

1. Geometry payload extension + Layer 2/3 in worker + summary counts (2–3 d)
2. `ColumnSymbol` SVG w/ states + drag/rotate + PATCH wiring (3 d)
3. Validation overlay + error badges + explorer/QA integration (2 d)
4. Missing-column suggestions + confirm flow (2 d)
5. Raster fallback behind `COLUMN_RASTER=1` flag + eval metrics (3 d)

*Ambiguities to confirm before build:* skewed-column support (non-orthogonal grids) — include in L2 quantization or defer; whether suggested ghosts should appear in the Sheet Summary counts (recommended: separate "Suggested" row).
