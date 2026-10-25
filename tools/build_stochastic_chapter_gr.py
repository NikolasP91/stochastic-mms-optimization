"""Build the Greek teaching chapter on stochastic programming for RDAS.

Source content lives in docs/chapter_gr/*.json (one file per section, sorted by
name). Each file is {"title": str, "blocks": [...]} where a block is one of:

  {"type": "paragraph", "text": "..."}            inline **bold**, *italic*, `code`, $math$
  {"type": "heading", "level": 2|3, "text": "..."}
  {"type": "equation", "latex": "..."}            numbered display equation
  {"type": "bullets"|"numbered", "items": ["...", ...]}
  {"type": "table", "caption": "...", "header": [...], "rows": [[...], ...]}
  {"type": "box", "kind": "definition"|"example"|"note"|"warning"|"code-map",
   "title": "...", "blocks": [...]}
  {"type": "figure", "file": "name.png", "caption": "...", "width_cm": 15}
  {"type": "code", "language": "json"|"python"|"text", "text": "..."}

Math is LaTeX converted to MathML (latex2mathml) and then to native Word OMML
with Office's MML2OMML.XSL, so equations remain editable in Word.

Usage:
    python tools/build_stochastic_chapter_gr.py [--output PATH] [--xsl PATH] [--source DIR]
"""

import argparse
import json
import os
from pathlib import Path
import re

from docx import Document
from docx.enum.section import WD_ORIENT  # noqa: F401  (kept for page setup tweaks)
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
import latex2mathml.converter
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "chapter_gr"
DEFAULT_OUTPUT = ROOT / "docs" / "Κεφάλαιο_Στοχαστικός_Προγραμματισμός_RDAS.docx"
DEFAULT_XSL = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft Office" / "root" / "Office16" / "MML2OMML.XSL"

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
BOX_STYLE = {
    "definition": ("Ορισμός", "E8F0FB", "2F5597"),
    "example": ("Παράδειγμα", "EEF6EA", "38761D"),
    "note": ("Σημείωση", "F3F3F3", "595959"),
    "warning": ("Προσοχή", "FDF0E6", "B45F06"),
    "code-map": ("Αντιστοίχιση με τον κώδικα", "F4ECF7", "7030A0"),
}
INLINE = re.compile(r"(\$[^$]+\$|\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)")


class Builder:
    def __init__(self, xsl_path, source=SOURCE):
        self.source = Path(source)
        if not Path(xsl_path).exists():
            raise SystemExit(f"MML2OMML.XSL not found at {xsl_path}; pass --xsl")
        self.xslt = etree.XSLT(etree.parse(str(xsl_path)))
        self.doc = Document()
        self.section_no = 0
        self.equation_no = 0
        self.table_no = 0
        self.figure_no = 0
        self._setup_styles()

    # ------------------------------------------------------------------ setup
    def _setup_styles(self):
        section = self.doc.sections[0]
        section.page_height, section.page_width = Cm(29.7), Cm(21.0)
        section.left_margin = section.right_margin = Cm(2.3)
        section.top_margin = section.bottom_margin = Cm(2.2)
        styles = self.doc.styles
        normal = styles["Normal"]
        normal.font.name = "Calibri"
        normal.font.size = Pt(11)
        normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
        self._set_lang(normal.element.get_or_add_rPr(), "el-GR")
        normal.paragraph_format.space_after = Pt(6)
        normal.paragraph_format.line_spacing = 1.15
        for level, size, color in ((1, 17, "1F3864"), (2, 13.5, "2F5597"), (3, 12, "2F5597")):
            style = styles[f"Heading {level}"]
            style.font.name = "Calibri"
            style.font.size = Pt(size)
            style.font.bold = True
            style.font.color.rgb = RGBColor.from_string(color)
            style.element.rPr.rFonts.set(qn("w:asciiTheme"), "")
            style.element.rPr.rFonts.set(qn("w:hAnsi"), "Calibri")
            style.element.rPr.rFonts.set(qn("w:ascii"), "Calibri")
            style.paragraph_format.space_before = Pt(18 if level == 1 else 12)
            style.paragraph_format.space_after = Pt(6)
            style.paragraph_format.keep_with_next = True
        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self._field(footer, "PAGE")

    @staticmethod
    def _set_lang(rpr, lang):
        element = rpr.find(qn("w:lang"))
        if element is None:
            element = OxmlElement("w:lang")
            rpr.append(element)
        element.set(qn("w:val"), lang)
        element.set(qn("w:eastAsia"), lang)

    @staticmethod
    def _field(paragraph, instruction):
        run = paragraph.add_run()
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        text = OxmlElement("w:instrText")
        text.set(qn("xml:space"), "preserve")
        text.text = instruction
        separate = OxmlElement("w:fldChar")
        separate.set(qn("w:fldCharType"), "separate")
        placeholder = OxmlElement("w:t")
        placeholder.text = "…"
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        for element in (begin, text, separate, placeholder, end):
            run._r.append(element)

    # ------------------------------------------------------------------- math
    def omml(self, latex, display):
        # latex2mathml emits an unescaped "&" for aligned; array{rl} is equivalent here.
        latex = re.sub(r"\\begin\{align\*?\}|\\begin\{aligned\}", r"\\begin{array}{rl}", latex)
        latex = re.sub(r"\\end\{align\*?\}|\\end\{aligned\}", r"\\end{array}", latex)
        # Sized delimiters are unsupported by latex2mathml for braces; plain delimiters render fine.
        latex = re.sub(r"\\(?:Big|big|Bigg|bigg)[lr]?(\\\{|\\\}|[\[\]\(\)|])", r"\1", latex)
        latex = latex.replace(r"\Pr", r"\mathrm{Pr}")
        # bmatrix brackets do not stretch after MML2OMML; \left[ ... \right] becomes a Word delimiter.
        latex = latex.replace(r"\begin{bmatrix}", r"\left[\begin{matrix}").replace(r"\end{bmatrix}", r"\end{matrix}\right]")
        # MML2OMML drops <mspace>: express LaTeX spacing as Unicode spaces in text runs.
        for command, space in ((r"\qquad", "  "), (r"\quad", " "),
                               (r"\;", " "), (r"\:", " "), (r"\,", " "), (r"\ ", " ")):
            latex = latex.replace(command, r"\text{" + space + "}")
        # Upright operator names; display limits under sums/min/max as in textbooks.
        latex = re.sub(r"\\operatorname\*?\{([^}]*)\}", r"\\mathrm{\1}", latex)
        if display:
            latex = re.sub(r"\\(sum|prod|min|max)(?!\\limits)\s*_", r"\\\1\\limits_", latex)
        latex = re.sub(r"\\(min|max)(?![A-Za-z]|\\limits)(?!\s*_)", r"\\mathrm{\1}", latex)
        try:
            mathml = latex2mathml.converter.convert(latex, display="block" if display else "inline")
            result = self.xslt(etree.fromstring(mathml.encode("utf-8")))
        except Exception as exc:  # noqa: BLE001 - report the failing formula
            raise ValueError(f"Cannot convert LaTeX: {latex!r}: {exc}") from exc
        root = result.getroot()
        if root is None:
            raise ValueError(f"Empty OMML for {latex!r}")
        # Multi-letter Latin runs (min, max, CVaR, ...) are operator names: upright.
        for run in root.iter(f"{{{M_NS}}}r"):
            text = "".join(t.text or "" for t in run.iter(f"{{{M_NS}}}t"))
            if len(text) > 1 and text.isascii() and text.isalpha():
                rpr = run.find(f"{{{M_NS}}}rPr")
                if rpr is None:
                    rpr = etree.Element(f"{{{M_NS}}}rPr")
                    run.insert(0, rpr)
                for old in rpr.findall(f"{{{M_NS}}}sty"):
                    rpr.remove(old)
                sty = etree.SubElement(rpr, f"{{{M_NS}}}sty")
                sty.set(f"{{{M_NS}}}val", "p")
        return root

    # ----------------------------------------------------------------- inline
    def add_inline(self, paragraph, text, *, bold=False, italic=False, size=None, color=None):
        for part in INLINE.split(text):
            if not part:
                continue
            if part.startswith("$") and part.endswith("$") and len(part) > 2:
                paragraph._p.append(self.omml(part[1:-1], display=False))
                continue
            run_bold, run_italic, mono = bold, italic, False
            if part.startswith("**") and part.endswith("**") and len(part) > 4:
                part, run_bold = part[2:-2], True
            elif part.startswith("`") and part.endswith("`") and len(part) > 2:
                part, mono = part[1:-1], True
            elif part.startswith("*") and part.endswith("*") and len(part) > 2:
                part, run_italic = part[1:-1], True
            run = paragraph.add_run(part)
            run.bold, run.italic = run_bold, run_italic
            if mono:
                run.font.name = "Consolas"
                run.font.size = Pt(9.5)
                run.font.color.rgb = RGBColor.from_string("7F2A00")
            if size:
                run.font.size = Pt(size)
            if color:
                run.font.color.rgb = RGBColor.from_string(color)

    # ----------------------------------------------------------------- blocks
    def paragraph(self, text, container=None, style=None, align=WD_ALIGN_PARAGRAPH.JUSTIFY):
        target = container if container is not None else self.doc
        p = target.add_paragraph(style=style)
        # Long unbreakable identifiers make justified lines gappy.
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT if text.count("`") >= 6 else align
        self.add_inline(p, text)
        return p

    def heading(self, text, level):
        if level == 1:
            self.section_no += 1
            self.equation_no = 0
            text = f"{self.section_no}. {text}"
        self.doc.add_heading(text, level=level)

    def equation(self, latex, container=None):
        self.equation_no += 1
        target = container if container is not None else self.doc
        table = target.add_table(rows=1, cols=2)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        widths = (Cm(14.2), Cm(2.0)) if container is None else (Cm(12.6), Cm(1.8))
        for cell, width in zip(table.rows[0].cells, widths):
            cell.width = width
        eq_cell, no_cell = table.rows[0].cells
        p = eq_cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        math = self.omml(latex, display=True)
        if math.tag != f"{{{M_NS}}}oMathPara":  # block MathML already yields oMathPara
            wrapper = etree.Element(f"{{{M_NS}}}oMathPara")
            wrapper.append(math)
            math = wrapper
        p._p.append(math)
        n = no_cell.paragraphs[0]
        n.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        n.add_run(f"({self.section_no}.{self.equation_no})")
        for cell in (eq_cell, no_cell):
            cell.vertical_alignment = 1  # center
        self._no_borders(table)

    def bullets(self, items, numbered=False, container=None):
        target = container if container is not None else self.doc
        for number, item in enumerate(items, 1):
            if numbered:
                # Explicit numbers: Word's List Number style would continue across lists.
                p = target.add_paragraph()
                p.paragraph_format.left_indent = Cm(0.75)
                p.paragraph_format.first_line_indent = Cm(-0.75)
                p.add_run(f"{number}.\t")
            else:
                p = target.add_paragraph(style="List Bullet")
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_after = Pt(3)
            self.add_inline(p, item)

    def table(self, block, container=None):
        target = container if container is not None else self.doc
        self.table_no += 1
        if block.get("caption"):
            cap = target.add_paragraph()
            cap.alignment = WD_ALIGN_PARAGRAPH.LEFT
            cap.paragraph_format.keep_with_next = True
            self.add_inline(cap, f"Πίνακας {self.section_no}.{self.table_no}: ", bold=True, size=10)
            self.add_inline(cap, block["caption"], size=10)
        header, rows = block["header"], block["rows"]
        table = target.add_table(rows=1 + len(rows), cols=len(header))
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, text in enumerate(header):
            cell = table.rows[0].cells[j]
            self._shade(cell, "D9E2F3")
            p = cell.paragraphs[0]
            self.add_inline(p, text, bold=True, size=9.5)
        for i, row in enumerate(rows, 1):
            if len(row) != len(header):
                raise ValueError(f"Table row width mismatch in {block.get('caption')!r}: {row}")
            for j, text in enumerate(row):
                p = table.rows[i].cells[j].paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                self.add_inline(p, str(text), size=9.5)
        self._repeat_header(table)
        target.add_paragraph().paragraph_format.space_after = Pt(2)

    def box(self, block):
        label, fill, color = BOX_STYLE[block.get("kind", "note")]
        table = self.doc.add_table(rows=1, cols=1)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = table.rows[0].cells[0]
        cell.width = Cm(16.4)
        self._shade(cell, fill)
        self._box_border(table, color)
        title = cell.paragraphs[0]
        title.paragraph_format.keep_with_next = True
        heading = label + (f": {block['title']}" if block.get("title") else "")
        self.add_inline(title, heading, bold=True, color=color)
        for inner in block["blocks"]:
            self.render(inner, container=cell)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)

    def figure(self, block):
        self.figure_no += 1
        path = self.source / "figures" / block["file"]
        if not path.exists():
            raise FileNotFoundError(path)
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(str(path), width=Cm(block.get("width_cm", 15)))
        cap = self.doc.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self.add_inline(cap, f"Σχήμα {self.section_no}.{self.figure_no}: ", bold=True, size=10)
        self.add_inline(cap, block["caption"], size=10, italic=True)

    def code(self, block, container=None):
        target = container if container is not None else self.doc
        table = target.add_table(rows=1, cols=1)
        cell = table.rows[0].cells[0]
        self._shade(cell, "F6F8FA")
        self._box_border(table, "BFBFBF")
        first = True
        for line in block["text"].rstrip("\n").split("\n"):
            p = cell.paragraphs[0] if first else cell.add_paragraph()
            first = False
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.0
            run = p.add_run(line if line else " ")
            run.font.name = "Consolas"
            run.font.size = Pt(8.5)
        target.add_paragraph().paragraph_format.space_after = Pt(2)

    def render(self, block, container=None):
        kind = block["type"]
        if kind == "paragraph":
            self.paragraph(block["text"], container=container)
        elif kind == "heading":
            if container is not None:
                raise ValueError("Headings cannot be nested in boxes")
            self.heading(block["text"], block["level"])
        elif kind == "equation":
            self.equation(block["latex"], container=container)
        elif kind in ("bullets", "numbered"):
            self.bullets(block["items"], numbered=kind == "numbered", container=container)
        elif kind == "table":
            self.table(block, container=container)
        elif kind == "box":
            if container is not None:
                raise ValueError("Boxes cannot be nested")
            self.box(block)
        elif kind == "figure":
            if container is not None:
                raise ValueError("Figures cannot be nested in boxes")
            self.figure(block)
        elif kind == "code":
            self.code(block, container=container)
        else:
            raise ValueError(f"Unknown block type {kind!r}")

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _shade(cell, fill):
        shading = OxmlElement("w:shd")
        shading.set(qn("w:val"), "clear")
        shading.set(qn("w:color"), "auto")
        shading.set(qn("w:fill"), fill)
        cell._tc.get_or_add_tcPr().append(shading)

    @staticmethod
    def _borders(table, spec):
        tbl_pr = table._tbl.tblPr
        borders = OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            element = OxmlElement(f"w:{edge}")
            value, size, color = spec.get(edge, ("nil", 0, "auto"))
            element.set(qn("w:val"), value)
            element.set(qn("w:sz"), str(size))
            element.set(qn("w:color"), color)
            borders.append(element)
        # OOXML requires schema order: tblBorders precedes shd/tblLayout/tblCellMar/tblLook.
        for existing in tbl_pr.findall(qn("w:tblBorders")):
            tbl_pr.remove(existing)
        successor = next((child for child in tbl_pr
                          if child.tag in {qn("w:shd"), qn("w:tblLayout"), qn("w:tblCellMar"), qn("w:tblLook")}), None)
        if successor is None:
            tbl_pr.append(borders)
        else:
            successor.addprevious(borders)

    def _no_borders(self, table):
        self._borders(table, {})

    def _box_border(self, table, color):
        line = ("single", 8, color)
        self._borders(table, {"top": line, "left": ("single", 24, color), "bottom": line, "right": line})

    @staticmethod
    def _repeat_header(table):
        tr_pr = table.rows[0]._tr.get_or_add_trPr()
        element = OxmlElement("w:tblHeader")
        element.set(qn("w:val"), "true")
        tr_pr.append(element)

    # ------------------------------------------------------------------ build
    def front_matter(self, meta):
        title = self.doc.add_paragraph(style="Title")
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title.add_run(meta["title"])
        if meta.get("subtitle"):
            sub = self.doc.add_paragraph(style="Subtitle")
            sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
            sub.add_run(meta["subtitle"])
        for line in meta.get("front_paragraphs", []):
            self.paragraph(line)
        toc_title = self.doc.add_paragraph()
        self.add_inline(toc_title, "Περιεχόμενα", bold=True, size=13, color="1F3864")
        toc = self.doc.add_paragraph()
        self._field(toc, 'TOC \\o "1-2" \\h \\z \\u')
        note = self.doc.add_paragraph()
        self.add_inline(note, "(Στο Word: δεξί κλικ στα περιεχόμενα → «Ενημέρωση πεδίου» για αριθμούς σελίδων.)",
                        italic=True, size=9, color="7F7F7F")
        note.runs[-1].add_break(WD_BREAK.PAGE)

    def build(self, output):
        meta_path = self.source / "_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.doc.core_properties.title = meta["title"]
        self.doc.core_properties.language = "el-GR"
        self.front_matter(meta)
        files = sorted(p for p in self.source.glob("*.json") if not p.name.startswith("_"))
        if not files:
            raise SystemExit(f"No section files in {self.source}")
        for path in files:
            section = json.loads(path.read_text(encoding="utf-8"))
            self.table_no = self.figure_no = 0
            self.heading(section["title"], 1)
            for block in section["blocks"]:
                try:
                    self.render(block)
                except Exception as exc:
                    raise SystemExit(f"{path.name}: {exc}") from exc
        output.parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(output)
        return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--xsl", type=Path, default=DEFAULT_XSL)
    parser.add_argument("--source", type=Path, default=SOURCE, help="Folder with _meta.json and section files")
    args = parser.parse_args(argv)
    path = Builder(args.xsl, args.source).build(args.output)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
