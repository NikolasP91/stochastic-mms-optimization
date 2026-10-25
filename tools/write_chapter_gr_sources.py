"""Write docs/chapter_gr/*.json from the Python sources in tools/chapter_gr_content.

Then build the Word file with tools/build_stochastic_chapter_gr.py.
"""

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
TARGET = ROOT / "docs" / "chapter_gr"


def main():
    package = ROOT / "tools" / "chapter_gr_content"
    TARGET.mkdir(parents=True, exist_ok=True)
    for old in TARGET.glob("*.json"):
        old.unlink()
    meta = importlib.import_module("chapter_gr_content.meta")
    (TARGET / "_meta.json").write_text(json.dumps(meta.META, ensure_ascii=False, indent=1), encoding="utf-8")
    for path in sorted(package.glob("s[0-9][0-9]_*.py")):
        module = importlib.import_module(f"chapter_gr_content.{path.stem}")
        section = {"title": module.TITLE, "blocks": module.BLOCKS}
        (TARGET / f"{path.stem}.json").write_text(json.dumps(section, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{path.stem}: {len(module.BLOCKS)} blocks")


if __name__ == "__main__":
    main()
