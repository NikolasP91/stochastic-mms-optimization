"""Make every string literal in the section modules raw (LaTeX backslashes).

Usage: python tools/chapter_gr_content/_rawify.py   (idempotent)
"""

import io
from pathlib import Path
import tokenize


def rawify(source):
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    edits = []
    for token in tokens:
        if token.type == tokenize.STRING:
            prefix = token.string[:token.string.index(token.string[-1])].lower()
            if "r" not in prefix:
                edits.append(offsets[token.start[0] - 1] + token.start[1])
    for position in reversed(edits):
        source = source[:position] + "r" + source[position:]
    return source


def main():
    for path in sorted(Path(__file__).parent.glob("s[0-9][0-9]_*.py")):
        text = path.read_text(encoding="utf-8")
        fixed = rawify(text)
        if fixed != text:
            path.write_text(fixed, encoding="utf-8")
            print(f"rawified {path.name}")


if __name__ == "__main__":
    main()
