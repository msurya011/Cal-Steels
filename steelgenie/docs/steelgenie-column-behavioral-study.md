# SteelGenie Column Extraction — Live Behavioral Study

Status: Phase 6 of the Column Engine mission. Observed live, 2026-07-15, against the
"CONGRESS HEIGHTS RC" project (app.steelgenie.com) — the same project CalSteel has been
tested against all session. This is a **behavioral study, not a source-code or
implementation inspection**: everything below was observed through the UI (Plans tab,
Source PDF overlay modes, Column Scheduler, Properties panel), never through inspecting
SteelGenie's code, network payloads, or internals.

Honest scope note: this pass studied one project in depth (Congress Heights RC, a
reinforced-concrete building with steel roof framing). The architecture doc
(`column-engine-architecture.md`) already has prior observations from Bayhealth Sussex
MOB (2026-07-09) which used a visually different column symbol (I/H tick mark, not a bare
hollow square) — that's referenced below where relevant, but was not re-verified live in
this pass. Multi-project breadth is flagged as a follow-up (see backlog item B7).

## 1. The real column symbol on this project's foundation plan

The "Source PDF" (raw, zero-overlay) view of Sheet S0101 (Foundation Plan) shows every
column/footing location marked with a **bare hollow square outline** — a plain 4-line
unfilled square, no inner tick mark, no fill, no diamond, no dot. The column's mark
(`F1`, `F1A`, `P2`, `P3`, `F4`, `F3A`, ...) is printed in a separate hexagonal bubble
positioned a short offset away from the square, never overlapping it.

This is a DIFFERENT symbol style from Bayhealth Sussex MOB, which (per the prior
2026-07-09 study) used a filled I/H plan-view tick mark. Confirms the mission's core
premise directly: **different projects really do use different column symbol
conventions**, even both being "foundation plans" from the AISC/US-structural-drawing
tradition. This one has no library entry conflict — it matches `sq_hollow_none` in
CalSteel's new Symbol Library (Phase 1), though see finding #2 below on how confidently
SteelGenie treats it.

## 2. Every hollow square with an adjacent real mark got detected — no visible misses

Switching to "Member Type" / "Estimating Scope" overlay mode (SteelGenie's own AI
annotation layer, drawn on top of the source PDF) shows a small **green dot centered
inside every hollow square** that has an `F`/`P`-prefixed mark bubble near it. Scanned
two full rows of the foundation plan (roughly 25 distinct footing locations): every
single hollow-square-plus-real-mark pairing got a green dot. No visible false negatives,
no visible extra green dots on shapes without a paired mark.

This is a strong signal that **on this project, mark-adjacency is doing most of the
acceptance work**, not shape alone — consistent with CalSteel's own
`filter_foundation_symbols_by_marks` design principle (radius-and-cap match against real
nearby marks), though SteelGenie's actual radius/pairing logic is invisible from the UI.

## 3. Brace footings (BF-prefixed marks) are drawn differently AND excluded

Marks like `BF-1`, `BF-2`, `BF-4` (brace-frame footings) are drawn with a distinct
**filled black diamond/bowtie icon**, visually different from the hollow square used for
regular footings — and none of them got a green detection dot in either overlay mode.
Two independent signals point the same direction here: a different SHAPE convention
(filled diamond vs. hollow square) AND a different MARK PREFIX (`BF` vs. bare
`F`/`P`/`C`). Can't fully separate which one SteelGenie is actually gating on from
observation alone, but the practical result — BF marks never become columns — matches
CalSteel's own behavior already: the `_MARK_RE` pattern (`^[FPC]\d{1,3}[A-Z]?$`) does
not match `BF-1` (starts with B), so CalSteel already excludes these too, for what
appears to be the same practical outcome via a different specific mechanism.

## 4. Detail/section callout bubbles are correctly ignored

Circular bubbles referencing another sheet (e.g. a cyan circle reading "9 / S0300") sit
directly adjacent to real footings in several places on this sheet and never get a green
dot. This is the exact false-positive pattern CalSteel's classifier's rule 1
(`DETAIL_MARKER`: circular shape + detail-reference text pattern) was built to reject —
directly confirms that rule's premise against live behavior, not just the architecture
doc's earlier note about it.

## 5. Column identity is GRID-POSITION-based, not mark-text-based — this is the biggest finding

The Column Scheduler (Columns tab) groups physical columns by shared vertical profile
into "Column Groups" (e.g. Column Group 1: columns `C1, C2, C3, C9`, grids
`D-9, D-7, D-8, D-10`). Expanding the group's member list shows each entry as
**`C1 (D-9)`, `C2 (D-7)`, `C3 (D-8)`, `C9 (D-10)`** — pairing an internal sequential ID
with a GRID COORDINATE, never with the plan's own printed mark (`F1`, `P2`, etc.).

**This means SteelGenie's actual column identity key is the grid intersection, not the
text printed on the drawing.** The plan's own `F1`/`P2`-style marks appear to function as
a secondary/cosmetic label for a human reading the sheet, not as the system's internal
column identifier. `C1`, `C2`, `C3`... are SteelGenie's own auto-assigned sequential IDs,
generated once per distinct physical column position, independent of whatever the
original PDF happened to print there.

This is a genuine, material gap against CalSteel's current architecture. CalSteel's
Global Column Database (`registration.py: sync_global_columns`) currently keys schedule
matching primarily on `plan_mark` text equality (mark match, falling back to profile
match) — see Phase 4 in the architecture doc. SteelGenie's real behavior suggests grid
position should be at least as authoritative an identity key as (or possibly more
authoritative than) the text mark. See backlog item B1.

## 6. No separate tabular "Column Schedule" PDF page on this project

Unlike Bayhealth Sussex MOB (which has a literal Column Schedule table, sheet S0400, per
the 2026-07-09 study), Congress Heights RC has no equivalent sheet in its 14-page PDF —
checked every page via the PDF viewer's page list. SteelGenie still produces full
Column Group data (profile per floor segment, base plate, anchors) for every column on
this project regardless. This confirms **SteelGenie doesn't strictly require a tabular
schedule page to produce column engineering data** — it can derive/compute this from the
plan + framing + elevation data across pages even without one. CalSteel's current
Phase 4 schedule parser (`column_schedule.py`) only produces base-plate/anchor/remarks
data when a literal schedule table exists; on schedule-less projects like this one,
CalSteel currently has no equivalent fallback. See backlog item B2.

## 7. Column splices are shown with an explicit "Welded Flange" label at the transition floor

Column Group 2 shows a single vertical run from Foundation (`hss8x8x3/8`) through Low
Roof, with a small editable **"Welded Flange"** label sitting exactly at the Low Roof
transition line — this is the field for the column's splice/connection method at that
segment boundary, directly editable by the user (pencil icon). Confirms the mission's
Phase 5 spec (`Column Splice Method` config options seen in the earlier product analysis:
Bolted Flange w/ Inner Plate, Bolted Flange, Welded Flange [default], Only Bolted Body) is
a real, live, per-column-group editable field, not just a global config default.

## 8. Framing-plan column representation: a colored vertical member bar, not a repeated icon

On the Low Roof Framing plan (Sheet S0102), the column at grid line 3 is rendered as a
**thick purple vertical bar** spanning the full visible bay height, labeled
`HSS8X8X3/8, TOS=197'-3"` at its top, with small blue square markers at its two grid
endpoints. This is visually distinct from the foundation plan's hollow-square-at-a-point
icon — on a framing plan the column reads as a MEMBER (a line with two endpoints and a
size label), matching how beams are drawn, not as a repeated point-symbol. This is
consistent with the architecture doc's existing "framing plan = reference, not
re-extraction" finding, and gives a concrete visual target for CalSteel's own framing-plan
column rendering (currently CalSteel doesn't render a distinct "this is the same DB
column, shown as a vertical run" treatment on framing plans — see Phase 7, still pending).

## 9. What this pass did NOT get to verify (explicitly out of scope for this report)

- Unlabeled-column confidence/warning UI on a live example (ran out of a clean case in
  this project — every visible footing had a real mark).
- Erection plan pages (this project's PDF set doesn't appear to include one distinct from
  the framing plans; not conclusively checked).
- OCR behavior on a raster/scanned drawing (this project's PDF appears to be a real vector
  PDF throughout).
- A second/third project's foundation-plan symbol style, live, in this same session (the
  2026-07-09 Bayhealth notes are being relied on secondhand for the I/H-tick-mark
  comparison in finding #1).
- Leader-arrow / dimension-tick / equipment-block / plumbing-symbol rejection specifically
  (none of these happened to sit close enough to a real mark on the areas of this sheet
  reviewed to test the boundary case directly).

These are natural next steps for a second behavioral-study pass, not gaps invented to
pad this list.
