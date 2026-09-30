"""Eval harness for the investigation agent. See evals/README.md.

Lives outside src/ on purpose: it's a development tool, not part of the
Lambda package, and it never touches real AWS (every trial runs against an
in-memory moto DynamoDB seeded with the demo data).
"""
