# Layer Filter & Summary Cards — Redesign Specification
**Product:** CalSteel takeoff workspace · **Date:** 2026-07-09 · ~1,500 words

**Basis:** feature-level observation of SteelGenie v1.5.1 (canvas toolbar exposes **Layer Filter** and **Color By** controls; right dock shows **Sheet Summary** metric rows — Column, Beam, Vertical/Horizontal Brace, Joists, Moment Connection, Bolt, Embed Plate, Camber, Weld Studs, Total Weight (tons), Hrs/Ton) and the current CalSteel code (`VerticalToolStrip`, `SheetSummary`, `SummaryBar`, selection/isolation store, `OverlayLayer`). SteelGenie's *panel internals* were not fully observable; where noted **[A]** the design follows standard CAD/BIM conventions.

---

## 1. What SteelGenie does (observed) vs. CalSteel today

| Aspect | SteelGenie | CalSteel current |
|---|---|---|
| Filter entry point | "Layer Filter" icon in canvas tool strip; opens a panel of member-class toggles **[A: contents inferred]** | No layer filter; per-member/per-kind hide + isolate exist in store (recent P3 work) but no organized panel |
| Color modes | "Color By" toolbar control | `colorMode` in store (kind/status/confidence) without dedicated UI |
| Summary | Right-docked Sheet Summary card, collapsible, with connection-level metrics; project-level totals above (Weld Studs, Total Weight, Hrs/Ton) | `SheetSummary` (added) + bottom `SummaryBar` chips; cards are display-only except chips |
| Overlay legend | Abbreviations toggle on canvas **[A]** | None |
| Persistence | Unknown **[A]** | None |

**Gap:** CalSteel has the *state machinery* (hiddenKinds/hiddenIds, isolation, colorMode) but no coherent **Layer Filter panel**, no presets/saved state, and summary cards that don't act as filters.

## 2. UI Mockups

### 2.1 Layer Filter panel (popover anchored to the tool strip)
A `Layers` icon joins the VerticalToolStrip. Clicking opens a 280px popover to its right:

```
┌─ LAYER FILTER ──────────────────────── ✕ ┐
│ 🔍 Filter layers…            [Presets ▾] │
├───────────────────────────────────────────┤
│ MEMBER CLASSES                            │
│ ● 👁 Beams (132)        ─ red             │
│ ● 👁 Columns (28)       ─ green           │
│ ● 👁 Vert. Braces (13)  ─ blue            │
│ ○ 🚫 Horiz. Braces (0)  ─ teal   (dimmed) │
│ ● 👁 Joists (4)         ─ violet          │
│ ● 👁 Unlabelled (7)     ─ dashed grey     │
├───────────────────────────────────────────┤
│ ANNOTATIONS & AIDS                        │
│ 👁 Manual markers   👁 Ruler lines        │
│ 👁 Member labels    ◻ Grid lines [A]      │
│ ◻ Confidence halo   ◻ Detection region    │
├───────────────────────────────────────────┤
│ COLOR BY   (Kind ▸ Status ▸ Confidence ▸  │
│             Section)                      │
│ Legend: ▬ W21X44 ▬ W12X26 ▬ HSS… (top 8)  │
├───────────────────────────────────────────┤
│ [Show All]  [Hide All]  [Invert]  [Save…] │
└───────────────────────────────────────────┘
```
Details: each class row = color swatch (click to recolor **[A]**, persisted), eye toggle, live count, opacity slider on hover (100→15%); rows with 0 members render dimmed; `Alt+click` an eye = solo that class (same isolate pipeline as the explorer); footer **Save…** creates a named preset. **Presets ▾** ships with defaults: *All*, *Steel only* (no annotations), *QA pass* (color-by confidence + halo on), *Braces check* (braces solo), plus user-saved entries.

### 2.2 Summary cards (right dock — evolution of current `SheetSummary`)
Keep the observed SteelGenie structure, make every row interactive:

```
┌ PROJECT TOTALS ────────────────────────┐
│ Weld Studs        333   │ live         │
│ Total Weight (t) 12.83  │ from shapes  │
│ Hrs/Ton           WIP   │ post-M4      │
├ SHEET SUMMARY ────────────────── ⌄ ────┤
│ ▸ Column          28   👁  ◎           │ ← hover reveals eye/isolate
│ ▸ Beam           132   👁  ◎           │
│ ▸ Vertical Brace  13   👁  ◎           │
│ … Moment Conn/Bolt/Embed/Camber: 0     │ (post-Build, greyed w/ tooltip)
│ Total Weight (tons)      [12.83]       │ highlighted chip
├ REVIEW ────────────────────────────────┤
│ ████████░░ 82% verified   ⚠ 7 remain   │ ← click ⚠ = filter Need Review
└────────────────────────────────────────┘
```
Row click = filter Member Explorer to that class; eye = layer toggle (same store slice as the panel — one source of truth); ◎ = isolate; weight row click opens BOM Grid pre-filtered to the sheet. A slim **project-level** variant of the same card appears on the BOM page header for continuity.

### 2.3 Canvas legend chip
When Color By ≠ Kind, a floating legend chip (bottom-left of canvas) lists the active palette (e.g., status colors). Click chip entries to toggle those members — legend doubles as a filter **[improvement beyond SteelGenie]**.

## 3. React Component Hierarchy

```
Workspace ([id]/page.tsx)
├─ VerticalToolStrip
│   └─ LayerFilterButton → <LayerFilterPopover>
│       ├─ LayerSearchInput
│       ├─ PresetMenu (defaults + user presets)
│       ├─ ClassLayerList → ClassLayerRow (swatch, EyeToggle, count, OpacitySlider)
│       ├─ AidLayerList → AidLayerRow (markers, rulers, labels, halo, region)
│       ├─ ColorModeSegment + PaletteLegend
│       └─ FooterActions (ShowAll/HideAll/Invert/SavePreset)
├─ PlanCanvas → OverlayLayer (consumes layers slice: visibility, opacity, colorMode)
│   └─ CanvasLegendChip
├─ SheetSummary (right dock)
│   ├─ ProjectTotalsRows
│   ├─ SheetSummarySection → SummaryRow (count, EyeToggle, IsolateToggle)
│   └─ ReviewProgressRow
└─ SummaryBar (bottom, existing) — reuses SummaryRow chips
```
Shared primitives: `EyeToggle`, `IsolateToggle`, `ColorSwatch`, `SummaryRow` live in `features/workspace/components/layers/` so the panel, summary cards, explorer, and bottom bar never re-implement toggle logic.

## 4. State Management

Extend `workspaceStore` with a **layers slice** (single source of truth for all four consumers):

```ts
layers: {
  classVisibility: Record<MemberKind | 'unlabelled', boolean>
  classOpacity:    Record<MemberKind, number>          // 0.15–1
  classColors:     Record<MemberKind, string>          // user-recolorable
  aids: { markers: boolean; rulers: boolean; labels: boolean;
          confidenceHalo: boolean; detectionRegion: boolean; grid: boolean }
  colorMode: 'kind' | 'status' | 'confidence' | 'section'
  activePresetId: string | null
}
presets: LayerPreset[]        // {id, name, layers snapshot}
```
Derived selector `getMemberRenderProps(member)` returns `{visible, opacity, color}` — `OverlayLayer` and the 3D view call only this (keeps overlay repaint <16 ms; memoize per colorMode+layers hash). Existing `hiddenKinds/hiddenIds/isolation` fold into this slice (isolation = temporary override, Esc restores). Persistence: layers + presets serialize to `localStorage` per project immediately; **saved presets** additionally sync to the backend (below) so they roam across devices. Compatibility contract: Member Explorer eyes, SheetSummary eyes, LayerFilter rows all write `classVisibility` — no component owns private visibility state; BOM Grid and 3D subscribe read-only (3D colors via the same `getMemberRenderProps`).

## 5. Backend / API Changes (small)

1. **`layer_presets` table**: `(id, user_id, project_id nullable, name, payload jsonb, created_at)` — project-scoped or global presets. CRUD: `GET/POST/PATCH/DELETE /projects/{id}/layer-presets` (single-table queries only — local mock DB has no joins).
2. **`GET /pages/{id}/members/summary`** (already specified for the explorer): counts by kind/status + top sections — powers panel counts and summary cards without full member payloads on big pages.
3. **No changes** to member endpoints; visibility/opacity/color are presentation state, never persisted per member.
4. Post-M4: build output feeds Moment Connection/Bolt/Embed/Camber/Stud rows; until then API returns them as `null` → UI greys with tooltip "Available after Build".

## 6. UX Details & Keyboard Map

`L` toggle Layer Filter panel · `Alt+click` eye = solo · `Alt+H` show all · `1–5` quick-toggle classes (beams/columns/vbraces/hbraces/joists) · `Shift+L` cycle Color By · panel is fully keyboard navigable (roving focus), ARIA `menu`/`switch` roles; color choices constrained to a colorblind-safe palette with pattern fallback (dashes for unlabelled). Responsiveness: below 1280px the right dock collapses to an icon rail; SheetSummary opens as an overlay sheet; the popover becomes a bottom drawer on narrow widths.

## 7. Prioritized Implementation Roadmap

| # | Scope | Effort | Acceptance |
|---|---|---|---|
| 1 | **Layers slice refactor** — fold hiddenKinds/ids + colorMode into `layers`, add `getMemberRenderProps`, wire OverlayLayer + Explorer + SheetSummary eyes to it | 2 d | Toggling any eye anywhere updates every surface; no regressions in isolate |
| 2 | **Layer Filter popover** — class rows, aids rows, Show/Hide/Invert, Color By segment, legend; `L` shortcut | 3 d | Hide columns from panel → canvas, explorer badge, summary row all reflect it |
| 3 | **Interactive summary cards** — hover eye/isolate on rows, click-to-filter, review progress row, BOM deep-link on weight | 2 d | Clicking "Beam" row filters explorer; ⚠ opens Need Review queue |
| 4 | **Presets & persistence** — defaults, save/rename/delete, localStorage + `layer_presets` API, per-project restore | 2 d | Reload restores last state; "QA pass" preset applies in one click |
| 5 | **Polish** — opacity sliders, recolor swatches, legend chip filter, canvas labels toggle, a11y + responsive pass | 2–3 d | Keyboard-only operation possible; 60 fps with 2,000 members |

Total ≈ 2 weeks, one frontend dev; backend ≈ ½ day (presets CRUD + summary endpoint already specced).

## 8. Assumptions
- SteelGenie Layer Filter panel contents were inferred from its toolbar affordances **[A]**; class toggles + aids grouping follow Revit/Bluebeam conventions.
- Hrs/Ton stays "WIP" until labor codes × build output exist (M4), matching the reference product's own WIP badge.
- Class color defaults mirror current overlay colors (beams red, columns green, braces blue) to avoid retraining users mid-project.
