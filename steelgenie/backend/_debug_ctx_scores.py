import sys, io, fitz, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import brace_classifier as bc
import inspect

doc = fitz.open('uploads/Structural snaps.pdf')
page = doc[2]

# Extract raw text blocks from the page
blocks = page.get_text("blocks")
print("=== ALL TEXT BLOCKS (first 60 chars) ===")
for b in blocks:
    txt = b[4].strip().replace('\n', ' ')
    if txt:
        print(f"  [{txt[:80]}]")

print()
print("=== classify_page_context result ===")
ctx, score = bc.classify_page_context(page)
print(f"  context={ctx}  score={score}")

doc.close()
