"""Source text of the Greek chapter. Each module sNN_*.py defines TITLE and BLOCKS.

Helpers build the JSON block format consumed by tools/build_stochastic_chapter_gr.py.
Inline math uses $...$ (LaTeX); display equations use EQ(r"...").
"""


def P(text):
    return {"type": "paragraph", "text": text}


def H(text, level=2):
    return {"type": "heading", "level": level, "text": text}


def EQ(latex):
    return {"type": "equation", "latex": latex}


def UL(*items):
    return {"type": "bullets", "items": list(items)}


def OL(*items):
    return {"type": "numbered", "items": list(items)}


def TAB(caption, header, rows):
    return {"type": "table", "caption": caption, "header": list(header), "rows": [list(r) for r in rows]}


def BOX(kind, title, *blocks):
    return {"type": "box", "kind": kind, "title": title, "blocks": list(blocks)}


def FIG(file, caption, width_cm=15):
    return {"type": "figure", "file": file, "caption": caption, "width_cm": width_cm}


def CODE(text, language="text"):
    return {"type": "code", "language": language, "text": text.strip("\n")}
