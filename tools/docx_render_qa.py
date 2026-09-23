from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


QA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"D:\college\Final-Year-Documentation\Code\.docx_qa\final_APA7")
prefix = sys.argv[2] if len(sys.argv) > 2 else "page"
pages = sorted(QA.glob(f"{prefix}-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
sheet_dir = QA / "contact_sheets"
sheet_dir.mkdir(exist_ok=True)

cols, rows = 5, 5
cell_w, cell_h = 330, 440
label_h = 28
font = ImageFont.load_default()

for sheet_index in range(math.ceil(len(pages) / (cols * rows))):
    subset = pages[sheet_index * cols * rows : (sheet_index + 1) * cols * rows]
    canvas = Image.new("RGB", (cols * cell_w, rows * cell_h), "#b8b8b8")
    draw = ImageDraw.Draw(canvas)
    for i, path in enumerate(subset):
        img = Image.open(path).convert("RGB")
        max_w, max_h = cell_w - 14, cell_h - label_h - 14
        scale = min(max_w / img.width, max_h / img.height)
        thumb = img.resize((int(img.width * scale), int(img.height * scale)))
        x0 = (i % cols) * cell_w + (cell_w - thumb.width) // 2
        y0 = (i // cols) * cell_h + label_h + (cell_h - label_h - thumb.height) // 2
        canvas.paste(thumb, (x0, y0))
        page_no = int(path.stem.split("-")[-1])
        draw.text(((i % cols) * cell_w + 8, (i // cols) * cell_h + 7), f"Page {page_no}", fill="black", font=font)
    out = sheet_dir / f"sheet-{sheet_index + 1:02d}.png"
    canvas.save(out)

print(f"pages={len(pages)} sheets={math.ceil(len(pages)/(cols*rows))} dir={sheet_dir}")
