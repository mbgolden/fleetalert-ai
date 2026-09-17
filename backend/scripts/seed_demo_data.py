"""One-off script to load the fixed demo scenarios into the real AWS tables.

Not part of the Lambda package (lives outside src/fleetalert) -- this is a
dev-time utility, run by hand with real AWS credentials (CLI profile,
CloudShell, etc):

    cd backend && uv run python scripts/seed_demo_data.py

Safe to re-run: every write here is a put_item, which overwrites by
primary key rather than erroring on a duplicate.
"""

from __future__ import annotations

from fleetalert.repositories import create_alert, put_knowledge_base_entry, put_machine
from fleetalert.seed_data import SEED_ALERTS, SEED_KNOWLEDGE_BASE, SEED_MACHINES


def main() -> None:
    for machine in SEED_MACHINES:
        put_machine(machine)
        print(f"put machine {machine['machine_id']}")

    for entry in SEED_KNOWLEDGE_BASE:
        put_knowledge_base_entry(entry)
        print(f"put knowledge base entry {entry['kb_id']}")

    for alert in SEED_ALERTS:
        create_alert(alert)
        print(f"put alert {alert['alert_id']}")


if __name__ == "__main__":
    main()
