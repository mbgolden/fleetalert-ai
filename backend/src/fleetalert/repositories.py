"""Table creation (for tests/local dev) and repository functions.

Table schemas here must stay in sync with infra/modules/dynamodb/main.tf —
this is the moto/local-dev equivalent of what Terraform provisions in AWS.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from fleetalert.db import (
    ALERTS_TABLE,
    KNOWLEDGE_BASE_TABLE,
    MACHINES_TABLE,
    TELEMETRY_TABLE,
    TRACES_ALERT_INDEX,
    TRACES_TABLE,
    USAGE_TABLE,
    get_dynamodb_resource,
)


def _dynamo_safe(value: Any) -> Any:
    """Recursively convert float -> Decimal; DynamoDB has no float type.

    Applied at the boundary just before put_item/update_item so callers
    (e.g. the agent loop, which gets a plain float `confidence` straight
    from the model's tool call) never have to think about this.
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _dynamo_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_dynamo_safe(v) for v in value]
    return value


def create_tables() -> None:
    ddb = get_dynamodb_resource()

    ddb.create_table(
        TableName=MACHINES_TABLE,
        KeySchema=[{"AttributeName": "machine_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "machine_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName=TELEMETRY_TABLE,
        KeySchema=[
            {"AttributeName": "machine_id", "KeyType": "HASH"},
            {"AttributeName": "timestamp", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "machine_id", "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName=ALERTS_TABLE,
        KeySchema=[{"AttributeName": "alert_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "alert_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName=KNOWLEDGE_BASE_TABLE,
        KeySchema=[{"AttributeName": "kb_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "kb_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName=TRACES_TABLE,
        KeySchema=[
            {"AttributeName": "trace_id", "KeyType": "HASH"},
            {"AttributeName": "span_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "trace_id", "AttributeType": "S"},
            {"AttributeName": "span_id", "AttributeType": "S"},
            {"AttributeName": "alert_id", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": TRACES_ALERT_INDEX,
                "KeySchema": [
                    {"AttributeName": "alert_id", "KeyType": "HASH"},
                    {"AttributeName": "span_id", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    ddb.create_table(
        TableName=USAGE_TABLE,
        KeySchema=[{"AttributeName": "day", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "day", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


def put_machine(machine: dict[str, Any]) -> None:
    get_dynamodb_resource().Table(MACHINES_TABLE).put_item(Item=_dynamo_safe(machine))


def get_machine(machine_id: str) -> dict[str, Any] | None:
    resp = get_dynamodb_resource().Table(MACHINES_TABLE).get_item(Key={"machine_id": machine_id})
    item: dict[str, Any] | None = resp.get("Item")
    return item


def get_service_history(machine_id: str) -> list[dict[str, Any]]:
    machine = get_machine(machine_id)
    if machine is None:
        return []
    result: list[dict[str, Any]] = machine.get("service_history", [])
    return result


def put_telemetry_reading(
    machine_id: str, timestamp: str, signal_readings: dict[str, Any]
) -> None:
    get_dynamodb_resource().Table(TELEMETRY_TABLE).put_item(
        Item=_dynamo_safe(
            {"machine_id": machine_id, "timestamp": timestamp, "signal_readings": signal_readings}
        )
    )


def put_telemetry_readings(readings: list[dict[str, Any]]) -> None:
    """Bulk version of put_telemetry_reading, for seeding."""
    with get_dynamodb_resource().Table(TELEMETRY_TABLE).batch_writer() as batch:
        for reading in readings:
            batch.put_item(Item=_dynamo_safe(reading))


def clear_telemetry(machine_id: str) -> None:
    """Deletes every reading for a machine. Only for the detector's own
    truck (fleetalert.autonomous), whose readings are regenerated each run."""
    table = get_dynamodb_resource().Table(TELEMETRY_TABLE)
    readings = _query_all(table, KeyConditionExpression=Key("machine_id").eq(machine_id))
    with table.batch_writer() as batch:
        for reading in readings:
            batch.delete_item(Key={"machine_id": machine_id, "timestamp": reading["timestamp"]})


def get_telemetry_snapshot(machine_id: str, start: str, end: str) -> list[dict[str, Any]]:
    table = get_dynamodb_resource().Table(TELEMETRY_TABLE)
    resp = table.query(
        KeyConditionExpression=Key("machine_id").eq(machine_id)
        & Key("timestamp").between(start, end)
    )
    result: list[dict[str, Any]] = resp.get("Items", [])
    return result


def put_knowledge_base_entry(entry: dict[str, Any]) -> None:
    get_dynamodb_resource().Table(KNOWLEDGE_BASE_TABLE).put_item(Item=_dynamo_safe(entry))


# A tiny, explicit normalization table instead of a stemmer or embeddings:
# the KB is a handful of entries, and matching has to be deterministic so
# the eval harness sees the same results every run. See ADR-0010 for the
# bug this replaced (exact substring matching never matched "coolant
# temperature spike" against "coolant temp spike").
_SYNONYMS = {
    "temperature": "temp",
    "temperatures": "temp",
    "temps": "temp",
    "overheating": "temp",
    "overheat": "temp",
    "spiking": "spike",
    "spiked": "spike",
    "drifting": "drift",
    "drifted": "drift",
    "leaking": "leak",
    "leaks": "leak",
}
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is",
    "it", "no", "not", "of", "on", "or", "that", "the", "this", "to", "with",
    "alert", "issue", "problem",
}


def _tokens(text: str) -> set[str]:
    out = set()
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        word = _SYNONYMS.get(word, word)
        if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        if word not in _STOPWORDS:
            out.add(word)
    return out


def _kb_match_score(query: set[str], entry: dict[str, Any]) -> int:
    """0 means no match. Pattern-word overlap counts double.

    One shared word is never enough on its own (e.g. "temp" alone would pull
    a refrigeration "temperature drift" entry into a coolant query): it needs
    the whole pattern, two pattern words, or a pattern word plus a distinct
    description word.
    """
    pattern = _tokens(str(entry.get("issue_pattern", "")))
    description_only = _tokens(str(entry.get("description", ""))) - pattern
    pattern_hits = len(pattern & query)
    description_hits = len(description_only & query)
    matched = (
        (pattern and pattern <= query)
        or pattern_hits >= 2
        or (pattern_hits >= 1 and description_hits >= 1)
    )
    return 2 * pattern_hits + description_hits if matched else 0


def search_knowledge_base(machine_type: str, symptom_description: str) -> list[dict[str, Any]]:
    """Word-overlap match over KB entries for a machine type, best first.

    Still deliberately simple -- it's *supposed* to surface the seeded
    ambiguous scenario's conflicting entries rather than silently picking
    one, so the agent loop has to reckon with the conflict.
    """
    table = get_dynamodb_resource().Table(KNOWLEDGE_BASE_TABLE)
    resp = table.scan()
    entries: list[dict[str, Any]] = resp.get("Items", [])
    query = _tokens(symptom_description)
    scored = [
        (_kb_match_score(query, e), e) for e in entries if e.get("machine_type") == machine_type
    ]
    return [e for score, e in sorted(scored, key=lambda pair: -pair[0]) if score > 0]


def create_alert(alert: dict[str, Any]) -> None:
    get_dynamodb_resource().Table(ALERTS_TABLE).put_item(Item=_dynamo_safe(alert))


def get_alert(alert_id: str) -> dict[str, Any] | None:
    resp = get_dynamodb_resource().Table(ALERTS_TABLE).get_item(Key={"alert_id": alert_id})
    item: dict[str, Any] | None = resp.get("Item")
    return item


def list_alerts() -> list[dict[str, Any]]:
    """Demo alerts only: load-test alerts (fleetalert.loadtest) are excluded.

    Follows every page of the scan. It used to read only the first, which
    was fine for 7 alerts and would silently drop alerts once a load test
    pushed the table past one 1 MB page.
    """
    table = get_dynamodb_resource().Table(ALERTS_TABLE)
    return _scan_all(table, FilterExpression=Attr("load_test").not_exists())


def list_load_test_alerts(label: str) -> list[dict[str, Any]]:
    table = get_dynamodb_resource().Table(ALERTS_TABLE)
    return _scan_all(table, FilterExpression=Attr("load_test_label").eq(label))


def delete_alert(alert_id: str) -> None:
    get_dynamodb_resource().Table(ALERTS_TABLE).delete_item(Key={"alert_id": alert_id})


class ConcurrentUpdateError(Exception):
    """A conditional update_alert_if_current call lost a race.

    Means the alert's status no longer matches what the caller expected, or
    a newer write already landed since -- e.g. a retried Step Functions
    task arriving after an earlier attempt already completed the same
    transition. Callers decide what that means for them: an internal retry
    can treat it as "someone else already finished this" and move on, an
    externally-triggered call (a duplicate confirm/reject request) should
    usually treat it as a hard rejection.
    """


def update_alert(alert_id: str, **fields: Any) -> None:
    _update_alert(alert_id, fields)


def update_alert_if_current(
    alert_id: str, *, expected_status: str | list[str], **fields: Any
) -> None:
    """Atomic version of update_alert for status-transition writes.

    Only applies if the alert is still in `expected_status` (one status, or
    any of a list of acceptable prior statuses) AND no newer write has
    landed since (guarded by the monotonic `updated_at` stamp every update
    sets) -- both checked in one ConditionExpression, so there's no
    read-then-write gap for a concurrent writer to land in. Raises
    ConcurrentUpdateError instead of silently racing if either check fails.
    """
    now = datetime.now(UTC).isoformat()
    statuses = [expected_status] if isinstance(expected_status, str) else list(expected_status)
    condition_values: dict[str, Any] = {"now": now}
    placeholders = []
    for i, status in enumerate(statuses):
        key = f"expected_status_{i}"
        condition_values[key] = status
        placeholders.append(f":{key}")
    condition_expression = (
        f"#status IN ({', '.join(placeholders)}) "
        "AND (attribute_not_exists(updated_at) OR updated_at < :now)"
    )
    try:
        _update_alert(
            alert_id,
            fields,
            timestamp=now,
            condition_expression=condition_expression,
            condition_values=condition_values,
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ConcurrentUpdateError(
                f"Alert {alert_id} is not in status {statuses!r}, or a newer "
                "update has already landed"
            ) from exc
        raise


def _update_alert(
    alert_id: str,
    fields: dict[str, Any],
    *,
    timestamp: str | None = None,
    condition_expression: str | None = None,
    condition_values: dict[str, Any] | None = None,
) -> None:
    all_fields = {**fields, "updated_at": timestamp or datetime.now(UTC).isoformat()}
    table = get_dynamodb_resource().Table(ALERTS_TABLE)

    expr_names = {f"#{k}": k for k in all_fields}
    if condition_expression is not None:
        # the condition always references #status, even if this particular
        # update doesn't otherwise touch it
        expr_names["#status"] = "status"
    expr_values = {f":{k}": _dynamo_safe(v) for k, v in all_fields.items()}
    if condition_values:
        expr_values.update({f":{k}": _dynamo_safe(v) for k, v in condition_values.items()})
    update_expr = "SET " + ", ".join(f"#{k} = :{k}" for k in all_fields)

    kwargs: dict[str, Any] = {
        "Key": {"alert_id": alert_id},
        "UpdateExpression": update_expr,
        "ExpressionAttributeNames": expr_names,
        "ExpressionAttributeValues": expr_values,
    }
    if condition_expression:
        kwargs["ConditionExpression"] = condition_expression
    table.update_item(**kwargs)


def put_span(span: dict[str, Any]) -> None:
    """Append-only: refuses to overwrite an existing span."""
    get_dynamodb_resource().Table(TRACES_TABLE).put_item(
        Item=_dynamo_safe(span),
        ConditionExpression="attribute_not_exists(span_id)",
    )


def get_trace(trace_id: str) -> list[dict[str, Any]]:
    table = get_dynamodb_resource().Table(TRACES_TABLE)
    return _query_all(table, KeyConditionExpression=Key("trace_id").eq(trace_id))


def get_spans_for_alert(alert_id: str) -> list[dict[str, Any]]:
    """Every span for an alert across all its rounds, in order."""
    table = get_dynamodb_resource().Table(TRACES_TABLE)
    return _query_all(
        table, IndexName=TRACES_ALERT_INDEX, KeyConditionExpression=Key("alert_id").eq(alert_id)
    )


def clear_spans_for_alert(alert_id: str) -> None:
    """Demo Reset only -- the one path that deletes spans."""
    table = get_dynamodb_resource().Table(TRACES_TABLE)
    with table.batch_writer() as batch:
        for span in get_spans_for_alert(alert_id):
            batch.delete_item(Key={"trace_id": span["trace_id"], "span_id": span["span_id"]})


def prune_traces_for_alert(alert_id: str, *, keep: int) -> None:
    """Keeps only the alert's `keep` most recent traces (rounds).

    For the recurring email alert only (fleetalert.email_intake), so its
    history stays bounded; like clear_spans_for_alert, a demo-only delete
    (ADR-0015).
    """
    spans = get_spans_for_alert(alert_id)
    first_span: dict[str, str] = {}
    for span in spans:  # already in span_id (time) order
        first_span.setdefault(span["trace_id"], span["span_id"])
    newest_first = sorted(first_span, key=lambda trace_id: first_span[trace_id], reverse=True)
    stale = set(newest_first[keep:])
    if not stale:
        return
    table = get_dynamodb_resource().Table(TRACES_TABLE)
    with table.batch_writer() as batch:
        for span in spans:
            if span["trace_id"] in stale:
                batch.delete_item(Key={"trace_id": span["trace_id"], "span_id": span["span_id"]})


def _scan_all(table: Any, **kwargs: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _query_all(table: Any, **kwargs: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


# --- Daily usage (fleetalert.budget) ---


def put_load_test_run(label: str, record: dict[str, Any], *, if_new: bool = False) -> bool:
    """A load-test run's status, kept beside the usage rows. With if_new,
    refuses (returns False) if the label already has a record."""
    kwargs: dict[str, Any] = {"Item": _dynamo_safe({"day": f"loadtest-run#{label}", **record})}
    if if_new:
        kwargs["ConditionExpression"] = "attribute_not_exists(#day)"
        kwargs["ExpressionAttributeNames"] = {"#day": "day"}
    try:
        get_dynamodb_resource().Table(USAGE_TABLE).put_item(**kwargs)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise
    return True


def get_load_test_run(label: str) -> dict[str, Any] | None:
    resp = get_dynamodb_resource().Table(USAGE_TABLE).get_item(Key={"day": f"loadtest-run#{label}"})
    item: dict[str, Any] | None = resp.get("Item")
    return item


def list_all_load_test_alerts() -> list[dict[str, Any]]:
    table = get_dynamodb_resource().Table(ALERTS_TABLE)
    return _scan_all(table, FilterExpression=Attr("load_test").exists())


def get_usage(day: str) -> dict[str, Any]:
    resp = get_dynamodb_resource().Table(USAGE_TABLE).get_item(Key={"day": day})
    item: dict[str, Any] = resp.get("Item") or {"day": day}
    return item


def reserve_usage(day: str, *, max_rounds: int, max_cost_usd: float, expires_at: int) -> bool:
    """Atomically counts one more round for `day`, unless either cap is
    already reached. False means refused; nothing was counted."""
    try:
        get_dynamodb_resource().Table(USAGE_TABLE).update_item(
            Key={"day": day},
            UpdateExpression="ADD investigations :one SET expires_at = :exp",
            ConditionExpression=(
                "(attribute_not_exists(investigations) OR investigations < :max_rounds) "
                "AND (attribute_not_exists(cost_usd) OR cost_usd < :max_cost)"
            ),
            ExpressionAttributeValues={
                ":one": 1,
                ":exp": expires_at,
                ":max_rounds": max_rounds,
                ":max_cost": _dynamo_safe(max_cost_usd),
            },
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise
    return True


def add_usage_cost(day: str, cost_usd: float, *, expires_at: int) -> None:
    get_dynamodb_resource().Table(USAGE_TABLE).update_item(
        Key={"day": day},
        UpdateExpression="ADD cost_usd :cost SET expires_at = :exp",
        ExpressionAttributeValues={":cost": _dynamo_safe(round(cost_usd, 6)), ":exp": expires_at},
    )
