import pytest

from fleetalert.repositories import put_knowledge_base_entry, search_knowledge_base
from fleetalert.seed_data import SEED_KNOWLEDGE_BASE


@pytest.fixture
def seeded_kb(dynamodb_tables: None) -> None:
    for entry in SEED_KNOWLEDGE_BASE:
        put_knowledge_base_entry(entry)


def _ids(matches: list[dict[str, object]]) -> set[object]:
    return {m["kb_id"] for m in matches}


@pytest.mark.parametrize(
    "query",
    [
        "coolant temp spike",
        # The phrasing Claude actually used live -- exact substring matching
        # returned nothing for this, so the conflict never surfaced (ADR-0010).
        "coolant temperature spike diesel engine",
        "coolant_temp_spike",
        "coolant sensor faulty reading",
    ],
)
def test_coolant_queries_surface_both_conflicting_entries(seeded_kb: None, query: str) -> None:
    assert _ids(search_knowledge_base("diesel_engine", query)) == {"KB-001", "KB-002"}


def test_oil_pressure_query_matches_only_the_oil_entry(seeded_kb: None) -> None:
    assert _ids(search_knowledge_base("diesel_engine", "low oil pressure")) == {"KB-004"}


def test_unrelated_symptom_matches_nothing(seeded_kb: None) -> None:
    # ALERT-1005's compressor fault deliberately has no KB coverage.
    assert search_knowledge_base("refrigeration_unit", "compressor fault") == []


def test_machine_type_still_scopes_results(seeded_kb: None) -> None:
    assert _ids(search_knowledge_base("refrigeration_unit", "cabin temperature drift")) == {"KB-003"}
    assert search_knowledge_base("refrigeration_unit", "coolant temp spike") == []


def test_best_match_comes_first(seeded_kb: None) -> None:
    matches = search_knowledge_base("diesel_engine", "coolant sensor glitch transient spike")
    assert matches[0]["kb_id"] == "KB-001"
