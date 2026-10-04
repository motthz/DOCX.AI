"""commit-msg hook: impone i Conventional Commits (feat:, fix:, docs:, ...)."""

import re
import sys

PATTERN = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert|release)"
    r"(\([\w\-./]+\))?!?: .{3,}"
)


def main() -> int:
    with open(sys.argv[1], encoding="utf-8") as fh:
        first = fh.readline().strip()
    if first.startswith(("Merge ", "Revert ")) or PATTERN.match(first):
        return 0
    print(
        "Messaggio di commit non valido:\n  " + first + "\n"
        "Usa il formato 'tipo(ambito): descrizione', es.\n"
        "  feat(report): esportazione Excel riepilogativa\n"
        "  fix(ocr): corretta chiamata WinRT\n"
        "Tipi: feat fix docs style refactor perf test build ci chore revert release"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
