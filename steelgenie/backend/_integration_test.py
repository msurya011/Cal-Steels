"""
Golden-dataset regression test for the brace extraction engine.
Covers: context classification, false positive filters, brace config,
section label attachment, and final HIGH/MEDIUM counts.

Run:  python _integration_test.py
Pass: exit code 0, all assertions green
Fail: prints FAIL lines + exits with code 1
"""
import sys, io, fitz, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import brace_classifier as bc

# ── Golden dataset ────────────────────────────────────────────────────────────
# (path, pg_0indexed, scale_ratio, expected_ctx, expected_H, expected_M,
#  note: None means "any / not checked")
GOLDEN = [
    # Snaps framing plan p2 — 10 real HIGH X-braces, 0 MEDIUM (annotation pair removed)
    ("uploads/Structural snaps.pdf", 2, 96,
     "framing_plan", 10, 0, "snaps framing p2"),

    # 07comb — detail pages must be hard-rejected
    ("uploads/Latest_Structural dwg_Binder (Addendum-02).pdf", 7, 128,
     "detail", 0, 0, "07comb detail p7"),
    ("uploads/Latest_Structural dwg_Binder (Addendum-02).pdf", 8, 128,
     "detail", 0, 0, "07comb detail p8"),

    # Structural binder p7 — now framing_plan (was unknown), stairwell opening removed
    ("#Structural binder.pdf", 7, 64,
     "framing_plan", 2, 4, "binder framing p7"),

    # Structural binder p11 — framing_plan
    ("#Structural binder.pdf", 11, 64,
     "framing_plan", 3, 6, "binder framing p11"),

    # Bayhealth framing p5
    ("uploads/2026.03.27_Bayhealth Sussex MOB_DD Set_Structural.pdf", 5, 96,
     "framing_plan", 4, 12, "bayhealth framing p5"),

    # Spruce framing p3
    ("uploads/02 Struct 98 Spruce_2026-03-13_BID.pdf", 3, 96,
     "framing_plan", 8, 6, "spruce framing p3"),
]

# ── Run ───────────────────────────────────────────────────────────────────────
failures = []
total_h = total_m = 0

print(f"{'Label':30s}  {'ctx':20s}  H    M   {'configs':35s}  {'sections (sample)':25s}  status")
print("-" * 130)

docs = {}
for path, pg, scale, exp_ctx, exp_h, exp_m, label in GOLDEN:
    fpath = path if path.startswith("uploads/") else f"uploads/{path}"
    if fpath not in docs:
        docs[fpath] = fitz.open(fpath)
    doc   = docs[fpath]
    page  = doc[pg]
    ppf   = bc.scale_to_pts_per_foot(scale)

    ctx, _   = bc.classify_page_context(page)
    cands    = bc.extract_diagonals(page, ppf)
    scales   = bc.find_scale_annotations(page)
    nodes    = bc.extract_structural_nodes(page, ppf) if ctx in bc.NODE_CHECK_CONTEXTS else None
    openings = bc.extract_opening_regions(page)
    clfd     = bc.classify(cands, ctx, scales, ppf, nodes, openings)
    clfd     = bc.enrich_brace_results(clfd, page)

    h = sum(1 for c in clfd if c["confidence"] == "HIGH")
    m = sum(1 for c in clfd if c["confidence"] == "MEDIUM")
    total_h += h;  total_m += m

    accepted = [c for c in clfd if c["confidence"] in ("HIGH","MEDIUM")]
    cfgs   = sorted(set(c.get("config","?") for c in accepted))
    sects  = sorted(set(c["section_label"] for c in accepted if c.get("section_label")))
    cfg_str  = ",".join(cfgs)[:34]
    sect_str = ",".join(sects[:2])[:24]  if sects else "—"

    ok = (ctx == exp_ctx and h == exp_h and m == exp_m)
    status = "OK" if ok else "FAIL"
    if not ok:
        failures.append(f"  {label}: ctx={ctx}(exp={exp_ctx}) H={h}(exp={exp_h}) M={m}(exp={exp_m})")

    print(f"{label:30s}  {ctx:20s}  {h:3d}  {m:3d}  {cfg_str:35s}  {sect_str:25s}  {status}")

for doc in docs.values():
    doc.close()

print("-" * 130)
print(f"{'TOTAL':30s}  {'':20s}  {total_h:3d}  {total_m:3d}")
print()

if failures:
    print(f"FAILED ({len(failures)} assertion(s)):")
    for f in failures:
        print(f)
    sys.exit(1)
else:
    print(f"All {len(GOLDEN)} assertions passed.")
