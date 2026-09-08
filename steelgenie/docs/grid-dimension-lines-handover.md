# Grid Dimension Lines — Developer Handover

**File:** `steelgenie/backend/main.py` → `extract_grid_dimensions()` (currently starts ~line 3464)
**Consumers:** `main.py` `/analyse` (line ~8261), `app/api/v1/floors.py` `GET /pages/{id}/grid-dimensions` (line ~188), rendered by `steelgenie/frontend/features/workspace/components/PlanCanvas/DimensionLine.tsx`

## The problem

Beam/joist length is computed **purely from geometry and scale** — `compute_beam_span()` (main.py ~line 202) takes the two grid coordinates and `pts_per_foot`, does the math, and that's the length. It never looks at printed text on the sheet.

`extract_grid_dimensions()` does something different for the *value it displays*: it computes `calc_ft` from geometry/scale exactly like beams do, but then it searches nearby OCR'd text spans for a dimension string that looks close enough, and if it finds one, **it overrides `calc_ft` with the OCR'd value** (`final_ft = matched_ocr["val_ft"] if matched_ocr else calc_ft`). So the number the user sees is sometimes "what the sheet's text happened to say nearby," not "what the geometry and scale say" — inconsistent with beams, and a bad OCR match (misread digit, wrong nearby dimension, overall-length string leaking in) silently produces a wrong number with no visible sign anything's off.

Separately: the *position* of the dimension line (which margin/track it's drawn on) is decided by a "dominant bucket" scan of nearby printed dimension text. That part is fine to keep — it's what makes the line sit close to the sheet's real dimension string instead of floating in an arbitrary offset — but right now it only checks one side per axis (top for the number axis, right for the letter axis), so it's wrong on any sheet that dimensions the other way.

## Desired behavior

1. **Length is always scale-computed, never OCR-overridden.** `length_ft` and the displayed `text` come from `(grid2_coord - grid1_coord) / pts_per_foot`, full stop — same formula, same `pts_per_foot`, as `compute_beam_span()` uses for beams. OCR text may still be captured for QA (e.g. an `ocr_text` field, or a `source` flag that says whether a nearby OCR match *agreed* with the computed value), but it must never replace the computed number.

2. **`pts_per_foot` must be the page's actual selected scale — never a silent guess.** Trace the value passed into `extract_grid_dimensions()` back to its source (main.py ~line 7787): when `req.scale_ratio` is set (the scale the user picked for that page, `page.scale_num` from the frontend), it correctly uses `scale_to_pts_per_foot(req.scale_ratio)`. It only falls back to auto-detection or a hardcoded `9.0` (1/8"=1'-0") when no scale was set at all. Grid dimensions should refuse to guess: if the page has no confirmed scale, either skip grid-dimension extraction and surface that to the user ("set a scale for this page to see bay dimensions") or clearly flag the result as unverified — never present a number computed from a silently-assumed scale as if it were authoritative.

3. **Line position:** keep the dominant-bucket text-density scan (it's the right idea — snap the line to wherever the sheet's own dimension text actually clusters), but run it for **both** sides of each axis (top and bottom for the number axis; left and right for the letter axis) and pick whichever side has denser real dimension text, instead of assuming a fixed side. If no printed dimension text is found on either side, fall back to a small fixed offset just outside the plan bounds — this fallback only affects where the line is drawn, never the number on it.

4. **Continuous, every bay, both axes.** Every consecutive grid pair on both axes gets a segment — no skipped bays, no duplicate/near-duplicate segments from closely-spaced grid labels (e.g. `1, 1.9, 2` or `7, 7.1, 7.2`).

## Concrete changes

In `extract_grid_dimensions()`:

- Delete the override: change
  ```python
  final_text = matched_ocr["text"] if matched_ocr else ft_to_arch_str(calc_ft)
  final_ft = matched_ocr["val_ft"] if matched_ocr else calc_ft
  ```
  to
  ```python
  final_ft = calc_ft
  final_text = ft_to_arch_str(calc_ft)
  ```
  in both the vertical-axis loop and the horizontal-axis loop. Keep `matched_ocr` only to set the QA flag, e.g. `"source": "scale_verified" if matched_ocr and abs(matched_ocr["val_ft"] - calc_ft) <= tolerance else "scale_computed"`, and optionally add `"ocr_text": matched_ocr["text"] if matched_ocr else None` so a human can spot a sheet where OCR disagrees with geometry (useful for catching grid-detection bugs) without that disagreement ever silently changing the displayed number.

- Extend the `dominant_y` / `dominant_x` bucket scan to check the opposite side too (below the plan for the number axis, left of the plan for the letter axis) when the first side's candidate set is empty or clearly sparser, and use whichever side wins. This is a placement-only change — it must not touch `calc_ft`/`final_ft`.

- Add a guard at the call site (main.py ~line 7787, and the `floors.py` endpoint at ~line 188) that stamps whether `pts_per_foot` came from an explicit page scale or a guess, and pass that through so the grid-dimensions result (or the endpoint response) can reflect it — e.g. skip extraction, or tag every segment `"scale_source": "explicit"` vs `"scale_source": "guessed"`, so the frontend/user can tell the difference instead of it being invisible.

- Sanity-check the near-duplicate-grid case (`1, 1.9, 2`): confirm each is treated as its own bay (which is correct, `1.9` is presumably a real sub-grid) rather than merged — just verify the `dist_pt < 4.0` skip isn't accidentally dropping a legitimately tiny bay, or letting duplicate coordinate noise through as a phantom bay.

## Frontend (separate, smaller item)

`DimensionLine.tsx`: on tightly-spaced bays (e.g. B/B.2/B.3, C/C.1, C.4/C.6 on a busy sheet) the rotated labels currently overlap into an unreadable pile. Add a minimum-segment-length threshold below which the label is suppressed, offset outward with a leader line, or staggered — this is purely a rendering fix and doesn't touch the backend values above.

## Test checklist before calling this done

- [ ] Pick a sheet where you know the real bay dimensions by eye (printed on the sheet). Confirm every displayed grid-dimension number matches geometry × scale exactly — never a text-matched value that disagrees.
- [ ] Temporarily corrupt/blank the OCR text near one bay (or test on a raster/scanned sheet with poor OCR) and confirm the displayed number is unaffected — it should still be the correct scale-computed value.
- [ ] Open a page with no scale explicitly set and confirm grid-dimension extraction does NOT silently produce numbers based on the 9.0 pts/ft fallback — it should skip or clearly flag as unverified.
- [ ] Confirm both axes are drawn as one continuous chain, every consecutive grid pair present, on the correct side (test against a sheet with letters on the right, e.g. `2026.03.27_Bayhealth Sussex MOB_DD Set_Structural.pdf`, and one with them on the left).
- [ ] Confirm dense bay clusters (B/B.2/B.3 etc.) render readable labels, not an overlapping pile.

---

## UPDATE — Missing axis on irregular/stepped buildings (found after the above fix was applied)

**Symptom:** after applying the fixes above, one axis's dimension chain renders perfectly (e.g. the number axis, top — all bays continuous, values correct), but the **other axis (letters) produces zero dimension lines** — not partial, not misplaced, completely absent, on both the side that has real printed bubbles and its fallback.

**This is not a bug in `extract_grid_dimensions()`.** That function is working correctly for whatever grid lines it's handed. The bug is one layer up, in `extract_grid_lines()` (main.py ~line 3084), which is producing an empty (or <2-line) letter grid for this page in the first place. Both the OCR-matched loop and the no-OCR fallback in `extract_grid_dimensions()` are gated by `len(sorted_h) >= 2` / `len(sorted_v) >= 2` — if the upstream grid detection returns nothing, there's nothing downstream can do about it.

**Root cause — `_monotonic_filter()`** (main.py, defined just before it's called at `letter_pts = _monotonic_filter(_dominant_band(letter_pts))` / same for `number_pts`, ~line 3299-3300):

```python
def _monotonic_filter(pts, min_frac=0.75):
    ...
    inc = sum(1 for i in range(n) if vals[i + 1] >= vals[i])
    dec = sum(1 for i in range(n) if vals[i + 1] <= vals[i])
    frac = max(inc, dec) / n
    return pts if frac >= min_frac else []
```

If fewer than 75% of consecutive (position-sorted) bubble pairs are in strict ascending/descending label order, it drops the **entire label family** — returns `[]`, not a filtered subset. The intent (per its own docstring) is to reject a printed schedule/load table that isn't really a grid. The side effect: on a building with an irregular or stepped footprint — a wing set back from the main line, a grid line that only runs partway through the building instead of the full length/height, or local sub-grids added at specific bays (e.g. `1.5`, `B.2`) rather than uniformly across the whole structure — the real bubbles legitimately don't form one single monotonic sequence along one shared edge. This is normal, correct structural drafting practice, not noise. The filter can't currently tell the difference and throws the whole axis away.

**Required fix (in `extract_grid_lines()`, not in `extract_grid_dimensions()`):**

- Stop treating "not 75%+ monotonic as one sequence" as grounds to discard the entire family. A real grid axis can legitimately be made of multiple partial runs (e.g. a letter grid that only exists for part of the building's depth because that wing doesn't extend as far, or a numbered grid with local mid-bay additions).
- Instead of one global pass/fail, segment the bubble points into locally-consistent runs (each internally monotonic) and keep every run that's internally consistent, rather than requiring one run to cover 75% of all points combined.
- Do not assume a grid axis spans the plan's full min→max extent. A grid line's presence should be derived from where its bubble/label actually appears, not assumed to run edge-to-edge — `extract_grid_dimensions()`'s `sorted_v`/`sorted_h` lists, and the `min_h`/`max_h`/`min_v`/`max_v` bounds it derives from them, are only as good as this.
- Test specifically against a building with a stepped/notched/offset footprint (the sheet behind this update — University of Texas at Laredo, Education and Research Center, project no. A202500.00 — is a good repro case: it has an offset wing and a stair core notch, and its letter-axis grid is being dropped entirely).

### Test checklist for this update

- [ ] On the Laredo sheet (or any stepped-footprint sheet), confirm the letter axis now produces a non-empty, continuous dimension chain — not just the number axis.
- [ ] Confirm a grid family that is genuinely NOT a grid (e.g. a load schedule table's number column) is still correctly rejected — the fix should narrow what counts as "not monotonic enough to be one run," not disable the check entirely.
- [ ] Confirm a locally-added sub-grid (e.g. `B.2` inserted between `B` and `C`) is retained and produces its own correct bay-to-bay segment, not treated as noise.
- [ ] Re-run the original test checklist above (scale-computed values, no OCR override, continuous chain, correct side) on both axes once the letter axis is no longer being dropped.
