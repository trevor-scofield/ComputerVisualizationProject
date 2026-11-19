from pathlib import Path
import re

import pdfplumber
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "output" / "pdf" / "lamp_project_transfer_report.pdf"
OUT = ROOT / "output" / "pdf" / "lamp_project_transfer_report.docx"


def extract_blocks(pdf_path):
    blocks = []
    starts = (
        "Local Affine Multidimensional Projection",
        "Technical summary, critical evaluation",
        "Selected paper:",
        "1. Technical Summary",
        "High-dimensional projection",
        "LAMP has two stages.",
        "The constraint M^T",
        "2. Critical Evaluation",
        "LAMP combines",
        "A 2D map",
        "The interaction can add",
        "3. Project Transfer Specification",
        "3a. Schema Mapping",
        "The project studies",
        "Join tournament metadata",
        "3b. Approach Adaptation",
        "Build a Python prototype",
        "Make the paper's control-point",
        "Link both views:",
        "Compare untouched",
        "3c. Expected Results",
        "The linked views",
        "The method improves",
        "References",
        "Joia, P.,",
        "IEEE VIS 2011 paper record:",
    )
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            text = re.sub(r"\nSmash History \| LAMP Project Transfer\s+\d+\s*$", "", text)
            for line in text.splitlines():
                line = line.strip()
                if line:
                    if line.startswith(starts):
                        blocks.append(line)
                    elif blocks:
                        blocks[-1] += " " + line
                    else:
                        blocks.append(line)
    return blocks


def set_font(style, name, size, color, bold=None):
    style.font.name = name
    style._element.rPr.rFonts.set(qn("w:ascii"), name)
    style._element.rPr.rFonts.set(qn("w:hAnsi"), name)
    style.font.size = Pt(size)
    style.font.color.rgb = RGBColor(*color)
    if bold is not None:
        style.font.bold = bold


def add_page_number(paragraph):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    value = OxmlElement("w:t")
    value.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for element in (begin, instruction, separate, value, end):
        run._r.append(element)


blocks = extract_blocks(PDF)
if len(blocks) < 15 or blocks[0] != "Local Affine Multidimensional Projection":
    raise RuntimeError(f"Unexpected source report structure: {len(blocks)} blocks")

doc = Document()
section = doc.sections[0]
section.top_margin = Inches(0.72)
section.bottom_margin = Inches(0.72)
section.left_margin = Inches(0.82)
section.right_margin = Inches(0.82)

normal = doc.styles["Normal"]
set_font(normal, "Arial", 10, (36, 47, 58), False)
normal.paragraph_format.space_after = Pt(7)
normal.paragraph_format.line_spacing = 1.12
normal.paragraph_format.widow_control = True

title = doc.styles["Title"]
set_font(title, "Arial", 22, (20, 38, 58), True)
title.paragraph_format.space_after = Pt(5)
title.paragraph_format.keep_with_next = True

subtitle = doc.styles["Subtitle"]
set_font(subtitle, "Arial", 11, (83, 101, 120), False)
subtitle.paragraph_format.space_after = Pt(10)
subtitle.paragraph_format.keep_with_next = True

h1 = doc.styles["Heading 1"]
set_font(h1, "Arial", 14, (18, 92, 117), True)
h1.paragraph_format.space_before = Pt(12)
h1.paragraph_format.space_after = Pt(5)
h1.paragraph_format.keep_with_next = True
h1.paragraph_format.keep_together = True

h2 = doc.styles["Heading 2"]
set_font(h2, "Arial", 11, (36, 60, 89), True)
h2.paragraph_format.space_before = Pt(8)
h2.paragraph_format.space_after = Pt(4)
h2.paragraph_format.keep_with_next = True
h2.paragraph_format.keep_together = True

# Editable title block, preserving the original report's wording and scope.
doc.add_paragraph(blocks[0], style="Title")
doc.add_paragraph(blocks[1], style="Subtitle")
meta = doc.add_paragraph(blocks[2])
meta.paragraph_format.space_after = Pt(8)
for run in meta.runs:
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(83, 101, 120)

for block in blocks[3:]:
    if re.match(r"^\d+\.\s", block):
        doc.add_paragraph(block, style="Heading 1")
    elif re.match(r"^3[abc]\.\s", block):
        doc.add_paragraph(block, style="Heading 2")
    elif block == "References":
        doc.add_paragraph(block, style="Heading 1")
    else:
        p = doc.add_paragraph(block, style="Normal")
        if block.startswith("Joia, P.,") or block.startswith("IEEE VIS 2011 paper record:"):
            p.paragraph_format.left_indent = Inches(0.18)
            p.paragraph_format.first_line_indent = Inches(-0.18)
            p.paragraph_format.space_after = Pt(5)
            for run in p.runs:
                run.font.size = Pt(9)

# Add a simple, editable page-number footer.
footer = section.footer.paragraphs[0]
footer.alignment = WD_ALIGN_PARAGRAPH.LEFT
footer.paragraph_format.tab_stops.add_tab_stop(Inches(6.86), WD_TAB_ALIGNMENT.RIGHT)
left = footer.add_run("Smash History | LAMP Project Transfer\t")
left.font.name = "Arial"
left.font.size = Pt(8)
left.font.color.rgb = RGBColor(100, 117, 138)
add_page_number(footer)

doc.core_properties.title = "Local Affine Multidimensional Projection - Project Transfer Report"
doc.core_properties.subject = "Technical summary, critical evaluation, and Smash History project transfer specification"
doc.core_properties.author = "Smash History Project Team"
OUT.parent.mkdir(parents=True, exist_ok=True)
doc.save(OUT)
print(f"Created editable Word report: {OUT}")
