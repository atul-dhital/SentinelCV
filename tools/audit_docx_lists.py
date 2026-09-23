from __future__ import annotations

import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET


DOCX = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"D:\college\Final-Year-Documentation\docs\final.docx")
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = "{" + NS["w"] + "}"

with zipfile.ZipFile(DOCX) as zf:
    numbering = ET.fromstring(zf.read("word/numbering.xml"))
    document = ET.fromstring(zf.read("word/document.xml"))

abstract_formats = {}
for abstract in numbering.findall("w:abstractNum", NS):
    abstract_id = abstract.attrib[W + "abstractNumId"]
    formats = {}
    for lvl in abstract.findall("w:lvl", NS):
        ilvl = lvl.attrib[W + "ilvl"]
        fmt = lvl.find("w:numFmt", NS)
        formats[ilvl] = fmt.attrib.get(W + "val", "") if fmt is not None else ""
    abstract_formats[abstract_id] = formats

num_to_abstract = {}
for num in numbering.findall("w:num", NS):
    num_id = num.attrib[W + "numId"]
    abstract_id = num.find("w:abstractNumId", NS).attrib[W + "val"]
    num_to_abstract[num_id] = abstract_id

counts = Counter()
roman_items = []
unknown_items = []
manual_roman = []
for index, p in enumerate(document.findall(".//w:body/w:p", NS)):
    text = "".join(t.text or "" for t in p.findall(".//w:t", NS)).strip()
    ppr = p.find("w:pPr", NS)
    if ppr is not None:
        numpr = ppr.find("w:numPr", NS)
        if numpr is not None:
            num_id_el = numpr.find("w:numId", NS)
            ilvl_el = numpr.find("w:ilvl", NS)
            if num_id_el is not None:
                num_id = num_id_el.attrib[W + "val"]
                ilvl = ilvl_el.attrib[W + "val"] if ilvl_el is not None else "0"
                fmt = abstract_formats.get(num_to_abstract.get(num_id, ""), {}).get(ilvl, "unknown")
                counts[fmt] += 1
                if fmt in {"upperRoman", "lowerRoman"}:
                    roman_items.append((index, fmt, num_id, ilvl, text))
                if fmt == "unknown":
                    unknown_items.append((index, num_id, ilvl, text))
    if re.match(r"^(?:[IVXLCDM]{1,8}|[ivxlcdm]{1,8})[.)]\s+", text):
        manual_roman.append((index, text))

print("list_formats", dict(counts))
print("roman_numbered_items", len(roman_items))
for item in roman_items[:100]:
    print(item)
print("unknown_numbered_items", len(unknown_items))
for item in unknown_items[:100]:
    print(item)
print("manual_roman_items", len(manual_roman))
for item in manual_roman[:100]:
    print(item)
