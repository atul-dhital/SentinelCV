from __future__ import annotations

import difflib
import re
from pathlib import Path
from docx import Document


def canonical(path: Path) -> str:
    doc = Document(path)
    parts = []
    for p_el in doc.element.body.xpath(".//w:p"):
        parts.append("".join(p_el.xpath(".//w:t/text()")))
    text = " ".join(parts)
    text = re.sub(r"(?i)(?<!\w)(?:ii|iii|iv)\.\s+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


a = canonical(Path(r"D:\college\Final-Year-Documentation\docs\final.docx"))
b = canonical(Path(r"D:\college\Final-Year-Documentation\docs\final_APA7.docx"))
print(len(a), len(b))
for group in difflib.SequenceMatcher(None, a, b).get_opcodes():
    tag, i1, i2, j1, j2 = group
    if tag != "equal":
        print(tag, repr(a[max(0, i1-100):i2+100]), repr(b[max(0, j1-100):j2+100]))
