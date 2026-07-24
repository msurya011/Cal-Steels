# Column Engine: SteelGenie vs. CalSteel — Gap Analysis & Backlog

Companion to `steelgenie-column-behavioral-study.md` (read that first for the evidence
behind each row). Built per the user's explicit instruction: "Only after this comparison
should we implement the remaining validation rules. Every new heuristic should be
justified by observed behavior rather than assumptions."

## Feature-by-feature comparison

| Behavior | SteelGenie (observed) | CalSteel (current) | Gap |
|---|---|---|---|
| Foundation-plan symbol acceptance | Hollow square + adjacent real mark → accepted, no visible misses on the sample reviewed | `filter_foundation_symbols_by_marks` + Symbol Library `sq_hollow_none` entry — same core idea (shape + mark proximity) | **Aligned.** No change needed, but see B3 (confidence tuning) |
| Non-column footing types (BF-prefixed brace footings) | Different icon (filled diamond) AND excluded from column set | `_MARK_RE` already excludes non-F/P/C-prefixed marks; no library entry for filled-diamond-no-inner exists so it wouldn't match confidently either | **Aligned**, arrived at independently. No urgent change |
| Detail/section callout bubbles | Circular + sheet-ref text → excluded | Classifier rule 1 (`DETAIL_MARKER`) does exactly this | **Aligned** |
| **Column identity key** | **Grid intersection** (`C1 (D-9)`) — plan mark text is cosmetic, not the identity | **Plan mark text**, primary; profile, fallback (`sync_global_columns`: `plan_mark` match → `plan_profile` match) | **Real gap.** See B1 |
| Schedule data without a tabular schedule page | **Corrected 2026-07-15**: profile comes from whichever source is actually available — if the plan itself prints the profile directly next to the symbol (confirmed live on "Seismic High-Rise Building": every column piecemark C_1...C_43 shows a real size, e.g. `w14x211`, read with no warning, because the source PDF literally labels each column with its size on the sheet), SteelGenie reads it with full confidence. Only when NEITHER a schedule page NOR an on-sheet label exists (Congress Heights RC's footings) does it fall back to guessing — confirmed via a live example: piecemark `C_7`, section `hss9x9x3/8`, with the exact UI warning *"Section size of this member is guessed by the Steel Genie"* and Status `Need Review`. Base plate/anchor fields stay empty/locked in the guessed case (no source for them at all). | `emit_symbol_columns` already does exactly this two-path behavior (`has_label_match` → real profile; no match → `_guessed_profile` + `guessed: true` + amber warning) | **Not actually a gap — CalSteel's existing design already matches this.** B2 downgraded from "real gap" to confirmed-aligned; no longer a priority backlog item |
| Column splice method | Explicit editable per-segment field ("Welded Flange"), defaults to Welded Flange per the product's own Config tab | `sync_global_columns` merges `weld_size`/`material` from schedule when present; no explicit splice-method field, no default when schedule is silent | **Partial gap.** See B4 |
| Framing-plan column rendering | Vertical member bar with size label at member endpoints, distinct from the foundation-plan point-icon | Framing-plan columns currently rendered the same as foundation-plan columns (a point icon); Phase 7 (reference overlay) still pending | **Known, already tracked gap** (task #67 / backlog B5) |
| Confidence/warning UI for guessed columns | Not re-verified this pass (no clean unlabeled case found on this project) | `guessed` flag + amber warning already implemented, matches the 2026-07-09 study | **Unverified this pass**, not re-confirmed or contradicted |
| OCR on raster/scanned drawings | Not tested (no raster PDF available in the reviewed project) | No OCR pipeline exists for raster foundation plans currently | **Unknown gap**, open question carried over from architecture doc §6 |

## Prioritized backlog

Ordered by (a) how directly the finding is evidenced, (b) how much it affects the Global
Column Database's correctness, (c) implementation cost.

**B1 — Add grid-intersection as a first-class column identity key (High priority, well-evidenced)**
Today `sync_global_columns` clusters columns by real-world (X, Z) position, which is
*already* grid-intersection-equivalent in practice (two detections at the same physical
spot cluster together regardless of mark text) — so the core dedup logic is not wrong.
The gap is specifically in **schedule matching**: currently keyed on `plan_mark` text
equality first. Recommendation: add a grid-reference match tier
(e.g. `D-9`) as an equal-or-higher-priority schedule lookup key alongside mark, for
projects where a schedule keys itself by grid position rather than by mark text — this
requires the Column Schedule parser to also capture a grid-reference column if present.
Needs verification the ACTUAL Bayhealth-style schedule tables (which use mark-keyed
columns like "C-5A") are the norm and this project's SteelGenie-synthesized C1/C2 IDs are
SteelGenie's own construct, not something read off a source schedule page — since this
project has no such page, SteelGenie is necessarily generating C1/C2 itself. Don't
over-rotate on this until a project with BOTH a real schedule page AND grid-vs-mark
naming conflict is found. Treat as informative, not yet a proven bug.

**B2 — Schedule-less profile/base-plate derivation fallback (Medium priority, well-evidenced)**
**RESOLVED 2026-07-15, downgraded from the original write-up.** Confirmed directly (see
table above): SteelGenie has no hidden mechanism here. It reads the profile when the plan
prints it (Seismic High-Rise project, every column labeled on-sheet), and guesses +
flags `Need Review` when nothing on the plan or in a schedule gives it one (Congress
Heights RC footings) — base plate/anchor fields stay empty in the guessed case, exactly
matching what a real engineer would do without that information. This is already
CalSteel's design (`has_label_match` → real profile / `guessed` flag otherwise). No
implementation work needed here; removed as an active backlog item.

**B3 — Recalibrate Symbol Library confidence for `sq_hollow_none` (Low priority, direct evidence)**
Current entry: `foundation_only`, confidence 0.55, requires a real mark to become a
column candidate at all (per classifier rule 6c's `has_mark and library_conf >= 0.55`
threshold). Observed: on this project, EVERY hollow-square + mark pairing was accepted
by SteelGenie with no visible false negatives across the sample — consistent with
CalSteel's current gate (mark required) but doesn't tell us whether SteelGenie is doing
anything MORE permissive. No change recommended yet; note for future re-verification once
a schedule-less-hollow-square project with some intentionally-unlabeled footings is found.

**B4 — Default column splice method to "Welded Flange" when schedule is silent (Low priority)**
Matches the product's own documented default (Config tab, `steelgenie_product_analysis.md`
memory). Cheap, well-evidenced (both the Config default AND a live per-column-group field
observed). Straightforward to add to `sync_global_columns`'s row construction as a
fallback value.

**B5 — Framing-plan reference rendering as a vertical member bar (existing task #67)**
Now has a concrete visual target from this study (finding #8): a colored bar at member
endpoints with a size label, not a repeated point icon. No change to this backlog's
priority — already tracked — but the acceptance criteria for that task should reference
this behavioral finding directly instead of being designed from first principles.

**B6 — Verify BF-prefixed (and other non-column footing prefix) exclusion is intentional, not incidental**
CalSteel's current exclusion of `BF-1` etc. is a side effect of `_MARK_RE` requiring an
`F`/`P`/`C` prefix, not a deliberate "brace footings are not columns" rule. Functionally
correct today, but worth an explicit rule (with a comment citing this finding) rather than
relying on an incidental regex property that could break if `_MARK_RE` is ever loosened.
Very low cost, do alongside any other classifier touch-up.

**B7 — Second live behavioral-study pass on a different project (process backlog item, not code)**
This pass covered one project (RC/hollow-square style) in depth. Recommend one more pass
on a steel-column-symbol project (e.g. Bayhealth Sussex MOB, re-verified live rather than
relied on secondhand) specifically to test: unlabeled-column warning UI, a real tabular
Column Schedule page's mark-vs-grid keying, and framing-plan reference rendering up close.

## What this analysis deliberately does NOT recommend

No change to the mark-radius filter, the Symbol Classification Engine's rejection rules
(detail markers, grid bubbles, dimension symbols, wall footings), or the Column
Validation Engine's scoring weights — every one of those was independently corroborated
by this pass's live observations (findings #2–#4), not contradicted. Per the user's
explicit instruction to resist adding heuristics without observed justification, the
right move here is targeted (B1, B2, B4) rather than a broad rewrite.
