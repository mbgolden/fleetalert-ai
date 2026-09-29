"""CI gate: every capability and Lambda handler must ship with tests and docs.

Fails the build if:
- a registered capability is never invoked by name in a test,
- a registered capability has no contract doc in docs/capabilities/,
- a Lambda handler module isn't referenced by any test.

Run from backend/: `uv run python scripts/check_capability_coverage.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

from fleetalert.capabilities import default_registry

BACKEND = Path(__file__).resolve().parents[1]
CONTRACTS = BACKEND.parent / "docs" / "capabilities"


def main() -> int:
    tests_text = "\n".join(p.read_text() for p in (BACKEND / "tests").glob("test_*.py"))
    problems = []

    for capability in default_registry().all():
        if f'"{capability.name}"' not in tests_text:
            problems.append(f"capability {capability.name!r} is never invoked by name in a test")
        if not (CONTRACTS / f"{capability.name}.md").is_file():
            problems.append(
                f"capability {capability.name!r} has no contract doc at docs/capabilities/{capability.name}.md"
            )

    for handler in sorted((BACKEND / "src" / "fleetalert" / "handlers").glob("*_handler.py")):
        if handler.stem not in tests_text:
            problems.append(f"handler {handler.stem} is not referenced by any test")

    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        return 1
    print(f"ok: {len(default_registry().all())} capabilities and all handlers have tests and contracts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
