import sys, io, fitz, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import brace_classifier as bc
import os

# Scan all uploaded PDFs for framing_plan pages with MEDIUM candidates
# to find which PDF matches the screenshots (W24X94, W30X116, HSS12X6X3/8, DECK TYPE 1)
uploads = 'uploads'

target_texts = ['W24X94', 'W30X116', 'HSS12X6X3/8', 'DECK TYPE', 'HSS56X3', 'HSS5X6']

for fname in sorted(os.listdir(uploads)):
    if not fname.endswith('.pdf'):
        continue
    path = os.path.join(uploads, fname)
    try:
        doc = fitz.open(path)
    except:
        continue
    for pg in range(min(len(doc), 60)):
        page = doc[pg]
        text = page.get_text("text")
        hits = [t for t in target_texts if t in text]
        if len(hits) >= 2:
            ctx, score = bc.classify_page_context(page)
            print(f"{fname}  p{pg:02d}  ctx={ctx}  hits={hits}")
    doc.close()
