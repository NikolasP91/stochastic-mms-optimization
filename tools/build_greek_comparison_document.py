"""Translate the English comparison DOCX without flattening its Office Math.

Run: python tools/build_greek_comparison_document.py
     python tools/build_greek_comparison_document.py --check

The reviewed English-to-Greek mapping is in greek_comparison_translations.json.
Unknown source text fails explicitly so changes to the English report cannot
silently leave untranslated or stale prose. Requires lxml (installed with the
python-docx documentation dependency). Microsoft Word automation is not used.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile

from lxml import etree


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/MMS_Deterministic_vs_Stochastic_Comparison.docx"
OUTPUT = ROOT / "docs/MMS_Deterministic_vs_Stochastic_Comparison_GR.docx"
MAPPING = Path(__file__).with_name("greek_comparison_translations.json")
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "dc": "http://purl.org/dc/elements/1.1/",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
}
NUMBERS = re.compile(r"\d+(?:[.,]\d+)*")


def parse(value: bytes) -> etree._Element:
    return etree.fromstring(value, etree.XMLParser(resolve_entities=False))


def serialize(root: etree._Element) -> bytes:
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)


def text_of(paragraph: etree._Element) -> str:
    return "".join(paragraph.xpath(".//w:t/text()", namespaces=NS))


def translated_text(value: str | list[str]) -> str:
    return "".join(value) if isinstance(value, list) else value


def translate_math(value: str, mapping: dict) -> str:
    for source, target in mapping["equation_phrases"].items():
        value = value.replace(source, target)
    return value


def translate_paragraphs(root: etree._Element, translations: dict) -> int:
    count = 0
    for paragraph in root.xpath("//w:p", namespaces=NS):
        original = text_of(paragraph)
        if not original:
            continue
        if original not in translations:
            raise ValueError(f"Missing reviewed Greek translation for: {original!r}")
        value = translations[original]
        nodes = paragraph.xpath(".//w:t", namespaces=NS)
        if isinstance(value, list):
            if len(value) != len(nodes):
                raise ValueError(f"Changed source run layout for: {original!r}")
            parts = value
        else:
            # Single text nodes dominate the source. Explicit lists retain the
            # title's line break and the two paragraphs with a bold lead-in.
            parts = [value] + [""] * (len(nodes) - 1)
        for node, part in zip(nodes, parts):
            node.text = part
            if part.startswith(" ") or part.endswith(" "):
                node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        count += 1
    return count


def set_language(root: etree._Element) -> None:
    for language in root.xpath("//w:lang", namespaces=NS):
        language.set(f"{{{NS['w']}}}val", "el-GR")
    if root.tag == f"{{{NS['w']}}}styles":
        defaults = root.find(f"{{{NS['w']}}}docDefaults")
        if defaults is None:
            defaults = etree.SubElement(root, f"{{{NS['w']}}}docDefaults")
        run_defaults = defaults.find(f"{{{NS['w']}}}rPrDefault")
        if run_defaults is None:
            run_defaults = etree.SubElement(defaults, f"{{{NS['w']}}}rPrDefault")
        props = run_defaults.find(f"{{{NS['w']}}}rPr")
        if props is None:
            props = etree.SubElement(run_defaults, f"{{{NS['w']}}}rPr")
        language = props.find(f"{{{NS['w']}}}lang")
        if language is None:
            language = etree.SubElement(props, f"{{{NS['w']}}}lang")
        language.set(f"{{{NS['w']}}}val", "el-GR")


def build(source: Path, output: Path, mapping: dict) -> None:
    if source.resolve() == output.resolve():
        raise ValueError("The Greek output must not overwrite the English source.")
    with ZipFile(source) as original:
        contents = {item.filename: original.read(item.filename) for item in original.infolist()}
        metadata = original.infolist()
    for name, value in list(contents.items()):
        is_story = name == "word/document.xml" or re.fullmatch(r"word/(header|footer)\d+\.xml", name)
        if is_story:
            root = parse(value)
            translate_paragraphs(root, mapping["paragraphs"] if name == "word/document.xml" else mapping["other_paragraphs"])
            for node in root.xpath("//m:t", namespaces=NS):
                node.text = translate_math(node.text or "", mapping)
            set_language(root)
            contents[name] = serialize(root)
        elif name == "word/styles.xml":
            root = parse(value)
            set_language(root)
            contents[name] = serialize(root)
        elif name == "docProps/core.xml":
            root = parse(value)
            for key, translated in mapping["metadata"].items():
                namespace = "cp" if key == "keywords" else "dc"
                node = root.find(f"{{{NS[namespace]}}}{key}")
                if node is None:
                    node = etree.SubElement(root, f"{{{NS[namespace]}}}{key}")
                node.text = translated
            language = root.find(f"{{{NS['dc']}}}language")
            if language is None:
                language = etree.SubElement(root, f"{{{NS['dc']}}}language")
            language.text = "el-GR"
            contents[name] = serialize(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Build to a sibling temporary file so failure never truncates an existing
    # reviewed document. The original ZIP metadata/compression are retained.
    temporary = output.with_suffix(".docx.tmp")
    try:
        with ZipFile(temporary, "w") as translated:
            for item in metadata:
                translated.writestr(item, contents[item.filename])
        validate(source, temporary, mapping)
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()


def structural_fingerprint(root: etree._Element) -> bytes:
    """Compare structure, styles, fields and mathematics, ignoring translations."""
    tree = deepcopy(root)
    for node in tree.xpath("//w:t|//m:t", namespaces=NS):
        node.text = ""
        node.attrib.pop("{http://www.w3.org/XML/1998/namespace}space", None)
    for language in tree.xpath("//w:lang", namespaces=NS):
        language.set(f"{{{NS['w']}}}val", "el-GR")
    return etree.tostring(tree, method="c14n")


def validate(source: Path, output: Path, mapping: dict) -> dict:
    with ZipFile(source) as original, ZipFile(output) as translated:
        if translated.testzip() is not None:
            raise ValueError("The translated DOCX has a corrupt ZIP member.")
        if original.namelist() != translated.namelist():
            raise ValueError("The document package parts changed.")
        story_names = [name for name in original.namelist() if name == "word/document.xml" or re.fullmatch(r"word/(header|footer)\d+\.xml", name)]
        total_paragraphs = 0
        for name in story_names:
            before, after = parse(original.read(name)), parse(translated.read(name))
            if structural_fingerprint(before) != structural_fingerprint(after):
                raise ValueError(f"Document structure or formatting changed in {name}.")
            source_paragraphs = before.xpath("//w:p", namespaces=NS)
            result_paragraphs = after.xpath("//w:p", namespaces=NS)
            translations = mapping["paragraphs"] if name == "word/document.xml" else mapping["other_paragraphs"]
            for source_p, result_p in zip(source_paragraphs, result_paragraphs):
                source_text, result_text = text_of(source_p), text_of(result_p)
                if not source_text:
                    continue
                if source_text not in translations:
                    raise ValueError(f"Unmapped source paragraph: {source_text!r}")
                if result_text != translated_text(translations[source_text]):
                    raise ValueError(f"Incorrect translation for: {source_text!r}")
                if Counter(NUMBERS.findall(source_text)) != Counter(NUMBERS.findall(result_text)):
                    raise ValueError(f"Numeric values changed in: {source_text!r}")
                total_paragraphs += 1
            for old, new in zip(before.xpath("//m:t", namespaces=NS), after.xpath("//m:t", namespaces=NS)):
                if (new.text or "") != translate_math(old.text or "", mapping):
                    raise ValueError("An editable equation has an unexpected change.")
        body = parse(translated.read("word/document.xml"))
        formula_count = len(body.xpath("//m:oMath", namespaces=NS))
        source_body = parse(original.read("word/document.xml"))
        if formula_count != len(source_body.xpath("//m:oMath", namespaces=NS)):
            raise ValueError("The number of editable equations changed.")
        table_count = len(body.xpath("//w:tbl", namespaces=NS))
        headings = body.xpath("//w:p[w:pPr/w:pStyle[@w:val='Heading1']]", namespaces=NS)
        if not parse(translated.read("word/styles.xml")).xpath("//w:docDefaults/w:rPrDefault/w:rPr/w:lang[@w:val='el-GR']", namespaces=NS):
            raise ValueError("The Greek proofing language is missing.")
        # Also let python-docx open the generated package; this verifies the
        # relationships and WordprocessingML beyond XML/ZIP well-formedness.
        from docx import Document
        reopened = Document(output)
        if len(reopened.tables) != table_count:
            raise ValueError("python-docx did not recover all translated tables.")
    return {
        "source": str(source),
        "output": str(output),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "validated_nonempty_paragraphs": total_paragraphs,
        "sections": len(headings),
        "tables": table_count,
        "editable_equations": formula_count,
        "structure_and_numeric_values_preserved": True,
        "proofing_language": "el-GR",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true", help="Validate the existing Greek document without rewriting it.")
    args = parser.parse_args()
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    if not args.check:
        build(args.source, args.output, mapping)
    print(json.dumps(validate(args.source, args.output, mapping), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
