#!/usr/bin/env python3
"""Flag non-ASCII characters in Markdown files.

Keeps the repo's `.md` consistent with the schema's ASCII conventions (e.g. `W/m2`,
`J/kg`, `^` for exponents) and keeps prose greppable/typeable. Used by the
`.githooks/pre-commit` hook (on staged files) and by CI (on all tracked `.md`).

Usage:
    python tools/check_ascii_md.py [FILE ...]     # check the given files
    python tools/check_ascii_md.py                # check every tracked *.md

Exit status: 0 if all clean, 1 if any non-ASCII character is found (each is printed
as `path:line:col: U+XXXX 'c'` with the offending line).
"""

import subprocess
import sys
from pathlib import Path

# Directories never worth scanning even if a stray .md lands in them.
_SKIP_PARTS = {".git", ".venv", "node_modules", "site-packages"}


def _tracked_markdown() -> list[str]:
    """Every *.md tracked by git; falls back to a filesystem walk outside a repo."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "*.md", "**/*.md"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        files = [ln for ln in out.splitlines() if ln.strip()]
        if files:
            return sorted(set(files))
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return sorted(
        str(p)
        for p in Path(".").rglob("*.md")
        if not _SKIP_PARTS.intersection(p.parts)
    )


def check_file(path: str) -> list[str]:
    """Return a list of human-readable findings for one file."""
    findings = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, IsADirectoryError):
        return findings
    for lineno, line in enumerate(lines, start=1):
        for col, ch in enumerate(line, start=1):
            if ord(ch) > 127:
                findings.append(
                    f"{path}:{lineno}:{col}: U+{ord(ch):04X} {ch!r}  |  {line.strip()}"
                )
    return findings


def main(argv: list[str]) -> int:
    files = argv or _tracked_markdown()
    findings = []
    for f in files:
        findings.extend(check_file(f))
    if findings:
        print("Non-ASCII characters found in Markdown (use ASCII, e.g. W/m2, ^2, --):")
        for line in findings:
            print(f"  {line}")
        print(f"\n{len(findings)} non-ASCII character(s) in {len(files)} file(s) checked.")
        return 1
    print(f"OK: no non-ASCII characters in {len(files)} Markdown file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
