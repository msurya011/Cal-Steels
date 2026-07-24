# Column Engine Architecture

Status: Phase 1 (research/documentation) — living document, updated as later phases land.
Scope: this document covers columns only. Beam/brace/joist/global-building engines are
explicitly out of scope until the Column Engine reaches production quality (see Development
Rule in the mission brief).

## 1. Why columns are the foundation

Every other structural element in a building either terminates at a column (beams, braces)
or is positioned relative to the column grid (joists, secondary framing). If column location,
mark, and profile data is wrong, every downstream engine inherits that error and has no way
to self-correct. This is why the Global Column Database is being treated as the single
source of truth that beam/brace/joist extraction must consume, not re-derive.

## 2. SteelGenie behavioral reference (live-verified, not reverse-engineered from source)

Everything in this section was observed directly against the live SteelGenie app across two
real projects (Congress Heights Recreation Center, Bayhealth Sussex Campus MOB) using browser
automation. CalSteel does not have access to SteelGenie's source code or internal algorithms —
these are behavioral observations, not implementation copies, per the mission's "reference,
not copy" instruction.

### 2.1 Foundation/plan pages — geometry + mark only

- SteelGenie extracts column *location* and *mark* (e.g. C2, C3, F1, F1A) from foundation and
  framing plan pages.
- It does **not** decode a section profile directly from the plan symbol on most sheets — plan
  marks usually don't carry the profile inline.
- Columns without a directly-readable profile render with a **guessed** profile and a visible
  warning affordance in the properties panel ("guessed by the Steel Genie" — CalSteel now
  mirrors this wording and the amber warning icon). The 2D plan symbol itself does **not**
  render in an alarming color for this — the guessed/needs-review signal lives in the
  properties panel, not as a loud red overlay on the drawing.

### 2.2 Framing plan pages — reference, not re-extraction

- When a column already identified on the foundation plan appears again on a framing plan
  (because framing beams land on it), SteelGenie shows the column symbol/mark as a reference
  to the already-known column. It does not appear to spin up a second, independently-tracked
  column for the same physical location.
- This was the direct motivation for CalSteel's Global Column Database: the "duplicate column"
  bug reported repeatedly this session was CalSteel treating every page's column-kind member
  as an independent 3D entity instead of recognizing the same physical column across pages.

### 2.3 Column Schedule pages — separate parsing path

- Directly confirmed live (sheet S0400, "Column Schedule", Bayhealth project): this is a
  literal table, not a plan drawing. Columns marks are table columns (C-5A, C-4A, ...), floor
  levels are rows (High Roof / Low Roof / Foundation), and each cell holds the profile for that
  column's segment at that floor — a column can change section partway up (e.g. HSS8X8X3/8
  transitioning to HSS8X8X1/2), plus base plate size, anchor bolts, and remarks.
- Critically: that sheet's own "Sheet Summary" panel showed **Column: 0, Beam: 0** — meaning
  SteelGenie explicitly does **not** run its normal plan-drawing vector-extraction pipeline
  against this sheet. It's read through a separate, table-specific parser. This confirms the
  architecture the mission brief specifies: Foundation Plan → Column Mark → Column Schedule →
  Column Database is a real, verified pattern, not a guess.

### 2.4 3D / grid behavior

- Every column runs from true grade up to its own real Top-of-Steel — verified against
  SteelGenie's own column scheduler (base = lowest real floor TOS, not an arbitrary world-zero
  clamp).
- Only **one** ground-level grid reference plane renders in the 3D view, not a repeated grid at
  every framing/roof level — confirmed by direct user comparison against the live app; CalSteel
  previously rendered a grid per floor, which looked wrong once more than one floor was loaded.

## 3. CalSteel's current implementation vs. this reference

| Piece | Status | Where |
|---|---|---|
| Foundation-plan symbol-only column detection (no beam-evidence gate) | Implemented | `main.py: detect_column_symbols(is_foundation_plan=True)`, `emit_symbol_columns(is_foundation_plan=True)` |
| Grid-envelope rejection (reject symbols outside the structural grid + slack) | Implemented | `main.py: emit_symbol_columns` |
| Mark-label-proximity filter, self-calibrated to sheet density | Implemented | `main.py: filter_foundation_symbols_by_marks()` — radius derived from median mark-to-mark spacing on that specific sheet, capped matches per mark (see §5) |
| Guessed-profile fallback (most common real profile in project, not a "COL" placeholder) | Implemented | `main.py: emit_symbol_columns` — `_guessed_profile` |
| Properties-panel warning icon for guessed sections | Implemented | `PropertiesPanel.tsx` |
| Global Column Database (dedup by real XZ position across all pages of a project) | Implemented | `registration.py: sync_global_columns()` |
| Column base/top elevation from real floor TOS + beam evidence | Implemented | `registration.py: sync_global_columns()` |
| Building-scope 3D reads columns from the Global DB, not raw per-page members | Implemented | `model.py` building-scope loop |
| Single ground-level grid only (not per-floor) | Implemented | `model.py` — grid emission deferred to lowest floor only |
| **Column Schedule table parser** (mark → floor segment → profile/plate/anchors/remarks) | **Not implemented** | Biggest structural gap — see Phase 4 task |
| **Merge schedule data into Global Column Database by mark** | **Not implemented** | Depends on schedule parser |
| **Framing-plan reference-only overlay** (show existing column, don't re-extract) | **Partially implemented** — 3D dedup exists; 2D per-page view still treats every page's symbol as its own independently-editable member, no "this is a reference to Foundation Plan's C2" UI treatment | See Phase 7 task |
| Cross-page confidence corroboration (mark seen on foundation + framing + schedule = higher confidence) | Not implemented | See Phase 6 |
| Automatic validation (duplicate marks, missing schedules, impossible elevations, etc.) | Not implemented | See Phase 6 task |
| Manual editing tools writing back to Global DB (merge/split duplicates, reassign schedule, etc.) | Not implemented | See Phase 8 task |
| Multi-project test suite | Not implemented — only tested against 2 real projects so far | See Phase 9 task |

## 4. Known failure modes found this session (with root causes)

These are documented here because they're the concrete evidence behind several "drawing-relative,
not magic-number" design decisions in the mission brief.

1. **Fixed pixel-radius mark matching doesn't generalize.** A 40pt radius (label directly
   touching its symbol) rejected every real column on a sheet where labels sit 50-235pt away
   via leader-line offset. Widening to 250pt fixed that sheet but over-matched on a denser
   sheet (147 detections against 77 real marks) because in a dense sheet, nearly every location
   is within a fixed radius of *some* real mark. Fix: derive the radius from that sheet's own
   median mark-to-mark spacing, and cap how many candidate symbols any single mark can "sponsor"
   (its nearest 2, not everyone in range).
2. **The general grid-line detector is not reliable enough to calibrate other logic against.**
   It reported 19 "vertical grid lines" on a sheet with ~9 real column lines. Any downstream
   logic (bay-width-derived radius, grid-envelope rejection) needs to tolerate or route around
   this noise rather than trusting it blindly.
3. **PDF dash-array metadata is not a reliable real-vs-fake signal.** A rule requiring
   `drawing["dashes"]` to be non-empty (to distinguish real dashed footing outlines from solid
   annotation boxes) silently rejected every real column on a PDF where the exporter didn't
   encode dash arrays in drawing metadata at all, even for genuinely dashed-looking footing
   marks. Replaced with the mark-label-proximity signal instead, which doesn't depend on
   PDF-exporter-specific metadata.
4. **A recurring file-truncation issue** (both `local_db.json` and, more seriously, `main.py`
   and `model.py` source files themselves) has repeatedly interrupted this session's work. The
   DB's own write path (`_save_db()`) is already correctly atomic (temp file + `os.replace()`),
   which means the truncation is very likely a sync-lag artifact between the Windows-side file
   and the sandbox's mounted view of it, not an application bug. Worth investigating
   independently of the Column Engine work, since it costs real time every time it recurs.

## 5. Design principle going forward: no unexplained magic numbers

Per the mission brief's explicit instruction, every threshold introduced in the Column Engine
from this point forward should be derived from the drawing itself (grid spacing, mark density,
symbol size relative to scale_ratio) rather than a hardcoded constant, OR — where a constant is
unavoidable (e.g. the `_CAP_PER_MARK = 2` in the mark-association filter) — it should be
documented with the reasoning and the real data it was calibrated against, so it can be
revisited when tested against a third/fourth/fifth real project reveals it doesn't generalize.

## 6. Open questions for Phase 2 onward

- Does SteelGenie use OCR at all for scanned/raster foundation plans, or only vector-PDF text
  layers? Not yet tested against a raster/scanned drawing live.
- How does SteelGenie handle a column whose mark changes between floors on the same physical
  location (e.g. a column that's C2 at foundation but referenced differently on an upper
  framing plan)? Not yet observed.
- Rotated/skewed grids: not yet tested against a real rotated-building project.
- Multiple Column Schedule pages in one project (continuation tables): not yet observed live.

These should be resolved by testing against additional real projects in Phase 1 (research)
before Phase 4 (schedule parser) is built, per the mission's sequencing.
