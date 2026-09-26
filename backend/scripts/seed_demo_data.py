"""One-off script to load the fixed demo scenarios into the real AWS tables.

Not part of the Lambda package (lives outside src/fleetalert) -- this is a
dev-time utility, run by hand with real AWS credentials (CLI profile,
CloudShell, etc):

    cd backend && uv run python scripts/seed_demo_data.py

Safe to re-run: every write here is a put_item, which overwrites by
primary key rather than erroring on a duplicate.
"""

from __future__ import annotations

from fleetalert.seed_data import reseed_demo_data


def main() -> None:
    reseed_demo_data()
    print("demo data reseeded")


if __name__ == "__main__":
    main()
