"""
Build a synthetic structural sheet that reproduces the missed-grid failure.

The geometry is taken from the S1.1 "First Floor - Dining Level Foundation &
Framing Plan" render, where grids D.1 and D.4 were visible on the sheet but
carried no measured span:

  * the plan does NOT fill the page -- a notes column sits on the left and a
    title block on the right, so the plan's own left margin lands about 27%
    across the page;
  * the letter axis has TWO rails on the left: an outer one at the far edge of
    the sheet, and a second, interior one carrying sub-grids where the
    building steps in.

Both facts matter, because `_build_axis_tracks` filters candidate bubbles with

    def near_edge(c):
        return (c["cx"] < pw * edge or c["cx"] > pw * (1 - edge) or ...)

with edge = 0.24 -- a test against the PAGE, not against the plan -- and then
allows only ONE band per side via `used_sides`. An interior rail fails both.

Run this, then run the deterministic pass over the output and check whether
C.1 and C.4 appear.
"""

import fitz

# 1/8" = 1'-0"  ->  0.125 * 72 = 9 points per foot.
PTS_PER_FOOT = 9.0
PAGE_W, PAGE_H = 1000.0, 700.0

# Vertical grid lines (numeric family), bubbles on the top and bottom rails.
NUMERIC = {"1": 300.0, "2": 390.0, "3": 480.0, "4": 615.0, "5": 750.0}

# Horizontal grid lines (letter family), bubbles on the OUTER left rail.
LETTER_OUTER = {"A": 100.0, "B": 190.0, "C": 280.0, "D": 460.0, "E": 550.0}

# The interior rail: sub-grids where the building steps in. Real grids, real
# lines, real dimensions -- but their bubbles sit at x = 280, which is 28% of
# the page width and therefore outside the 24% perimeter band.
LETTER_INNER = {"C.1": 340.0, "C.4": 400.0}
INNER_RAIL_X = 280.0
OUTER_RAIL_X = 60.0

PLAN_X0, PLAN_X1 = 270.0, 800.0
PLAN_Y0, PLAN_Y1 = 90.0, 560.0

BUBBLE_R = 9.0


def ft(pts):
    return pts / PTS_PER_FOOT


def arch(v):
    feet = int(v)
    inches = round((v - feet) * 12)
    if inches == 12:
        feet, inches = feet + 1, 0
    return f"{feet}'-{inches}\""


def bubble(page, x, y, label):
    """A grid bubble: a circle vector shape with the label centred in it."""
    page.draw_circle(fitz.Point(x, y), BUBBLE_R, color=(0, 0, 0), width=0.7)
    page.insert_text(fitz.Point(x - 3.6 * len(label) / 1.6, y + 2.6),
                     label, fontsize=6.5, color=(0, 0, 0))


def chain(page, p0, p1):
    """A grid line, drawn as a run of separate dashes the way CAD exports do."""
    page.draw_line(fitz.Point(*p0), fitz.Point(*p1),
                   color=(0.45, 0.45, 0.45), width=0.5, dashes="[9 3 2 3] 0")


def dim(page, a, b, coord, horizontal, offset):
    """A dimension line with ticks at each end and the value between them."""
    if horizontal:
        y = coord + offset
        page.draw_line(fitz.Point(a, y), fitz.Point(b, y), color=(0, 0, 0), width=0.4)
        for x in (a, b):
            page.draw_line(fitz.Point(x - 3, y + 3), fitz.Point(x + 3, y - 3),
                           color=(0, 0, 0), width=0.4)
        page.insert_text(fitz.Point((a + b) / 2 - 14, y - 3),
                         arch(ft(abs(b - a))), fontsize=6, color=(0, 0, 0))
    else:
        x = coord + offset
        page.draw_line(fitz.Point(x, a), fitz.Point(x, b), color=(0, 0, 0), width=0.4)
        for y in (a, b):
            page.draw_line(fitz.Point(x - 3, y - 3), fitz.Point(x + 3, y + 3),
                           color=(0, 0, 0), width=0.4)
        page.insert_text(fitz.Point(x + 2, (a + b) / 2),
                         arch(ft(abs(b - a))), fontsize=6, color=(0, 0, 0))


def build(path="repro_missing_grid.pdf"):
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)

    page.insert_text(fitz.Point(PLAN_X0, 45), "FIRST FLOOR - FOUNDATION & FRAMING PLAN",
                     fontsize=10, color=(0, 0, 0))
    page.insert_text(fitz.Point(PLAN_X0, 58), "SCALE: 1/8\" = 1'-0\"",
                     fontsize=7, color=(0, 0, 0))

    # Notes column on the left and a title block on the right -- the reason the
    # plan does not reach the page edges.
    page.insert_text(fitz.Point(30, 100), "GENERAL NOTES", fontsize=7)
    for i in range(14):
        page.insert_text(fitz.Point(30, 115 + i * 11),
                         f"{i+1}. SEE ARCHITECTURAL DRAWINGS FOR DIMENSIONS.", fontsize=5)
    page.draw_rect(fitz.Rect(820, 80, 980, 620), color=(0, 0, 0), width=0.7)
    page.insert_text(fitz.Point(830, 100), "MULTIPURPOSE BUILDING", fontsize=6)
    page.insert_text(fitz.Point(830, 600), "S1.1", fontsize=12)

    # --- vertical grid lines + top and bottom bubbles ---
    for label, x in NUMERIC.items():
        chain(page, (x, PLAN_Y0 - 45), (x, PLAN_Y1 + 45))
        bubble(page, x, PLAN_Y0 - 55, label)
        bubble(page, x, PLAN_Y1 + 55, label)
    xs = sorted(NUMERIC.values())
    for a, b in zip(xs, xs[1:]):
        dim(page, a, b, PLAN_Y0 - 40, horizontal=True, offset=0)

    # --- horizontal grid lines, OUTER left rail ---
    for label, y in LETTER_OUTER.items():
        chain(page, (OUTER_RAIL_X + 12, y), (PLAN_X1, y))
        bubble(page, OUTER_RAIL_X, y, label)
    ys = sorted(LETTER_OUTER.values())
    for a, b in zip(ys, ys[1:]):
        dim(page, a, b, OUTER_RAIL_X, horizontal=False, offset=25)

    # --- horizontal grid lines, INTERIOR rail (the ones that go missing) ---
    for label, y in LETTER_INNER.items():
        chain(page, (INNER_RAIL_X + 12, y), (PLAN_X1, y))
        bubble(page, INNER_RAIL_X, y, label)
    inner_chain = sorted(list(LETTER_INNER.values()) + [280.0, 460.0])
    for a, b in zip(inner_chain, inner_chain[1:]):
        dim(page, a, b, INNER_RAIL_X, horizontal=False, offset=22)

    # A little framing so the sheet is not just grids.
    page.draw_rect(fitz.Rect(PLAN_X0 + 20, PLAN_Y0 + 10, PLAN_X1 - 20, PLAN_Y1 - 10),
                   color=(0, 0, 0), width=1.2)

    doc.save(path)
    doc.close()

    print(f"wrote {path}")
    print("expected letter grids :", sorted(list(LETTER_OUTER) + list(LETTER_INNER)))
    print("expected numeric grids:", sorted(NUMERIC))
    print("interior rail bubbles at x =", INNER_RAIL_X,
          f"= {INNER_RAIL_X / PAGE_W:.0%} of page width (perimeter band is 24%)")
    return path


if __name__ == "__main__":
    build()
