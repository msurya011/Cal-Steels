import sys, io, fitz
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

doc = fitz.open('uploads/#Structural binder.pdf')
page = doc[7]
r = page.rect

# Title block: bottom 15%
title_clip = fitz.Rect(r.x0, r.y1 * 0.85, r.x1, r.y1)
title_text = page.get_text("text", clip=title_clip)
print("=== TITLE BLOCK TEXT ===")
print(title_text[:500])

# First 500 chars of full text
body_text = page.get_text("text")[:600]
print("\n=== BODY TEXT (first 600 chars) ===")
print(body_text)

# Also show last 300 chars
full_text = page.get_text("text")
print("\n=== LAST 300 chars ===")
print(full_text[-300:])

# Check all text blocks containing key terms
print("\n=== blocks with PLAN/FRAME/BRACE/OPENING ===")
import re
pat = re.compile(r'PLAN|FRAME|BRACE|OPENING|FRAMING', re.I)
for b in page.get_text("blocks"):
    if pat.search(b[4]):
        print(f"  [{b[4].strip()[:80]}]  y={b[1]:.0f}")

doc.close()
