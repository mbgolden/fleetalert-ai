"""Table creation (for tests/local dev) and repository functions.

Table schemas here must stay in sync with infra/modules/dynamodb/main.tf —
this is the moto/local-dev equivalent of what Terraform provisions in AWS.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from fleetalert.db import (
    ALERTS_TABLE,
    AUDIT_LOG_TABLE,
    KNOWLEDGE_BASE_TABLE,
    MACHINES_TABLE,
    TELEMETRY_TABLE,
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
        TableName=AUDIT_LOG_TABLE,
        KeySchema=[
            {"AttributeName": "alert_id", "KeyType": "HASH"},
            {"AttributeName": "timestamp", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "alert_id", "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
        ],
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


def search_knowledge_base(machine_type: str, symptom_description: str) -> list[dict[str, Any]]:
    """Keyword match over KB entries for a machine type.

    Deliberately simple (substring match against issue_pattern/description) —
    good enough for a small seeded KB, and it's *supposed* to surface the
    seeded ambiguous scenario's conflicting entries rather than silently
    picking one, so the agent loop has to reckon with it.
    """
    table = get_dynamodb_resource().Table(KNOWLEDGE_BASE_TABLE)
    resp = table.scan()
    entries: list[dict[str, Any]] = resp.get("Items", [])
    symptom_lower = symptom_description.lower()
    return [
        e
        for e in entries
        if e.get("machine_type") == machine_type
        and (
            symptom_lower in e.get("issue_pattern", "").lower()
            or symptom_lower in e.get("description", "").lower()
            or e.get("issue_pattern", "").lower() in symptom_lower
        )
    ]


def create_alert(alert: dict[str, Any]) -> None:
    get_dynamodb_resource().Table(ALERTS_TABLE).put_item(Item=_dynamo_safe(alert))


def get_alert(alert_id: str) -> dict[str, Any] | None:
    resp = get_dynamodb_resource().Table(ALERTS_TABLE).get_item(Key={"alert_id": alert_id})
    item: dict[str, Any] | None = resp.get("Item")
    return item


def list_alerts() -> list[dict[str, Any]]:
    resp = get_dynamodb_resource().Table(ALERTS_TABLE).scan()
    result: list[dict[str, Any]] = resp.get("Items", [])
    return result


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


def append_audit_log(
    alert_id: str, actor: str, action: str, details: dict[str, Any]
) -> dict[str, Any]:
    """Append-only: there is deliberately no update/delete for this table."""
    item = {
        "alert_id": alert_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "log_id": str(uuid.uuid4()),
        "actor": actor,
        "action": action,
        "details": details,
    }
    get_dynamodb_resource().Table(AUDIT_LOG_TABLE).put_item(Item=_dynamo_safe(item))
    return item


def get_audit_trail(alert_id: str) -> list[dict[str, Any]]:
    table = get_dynamodb_resource().Table(AUDIT_LOG_TABLE)
    resp = table.query(KeyConditionExpression=Key("alert_id").eq(alert_id))
    result: list[dict[str, Any]] = resp.get("Items", [])
    return result


def clear_audit_trail(alert_id: str) -> None:
    """Deletes every audit log entry for one alert -- used by the demo reset."""
    table = get_dynamodb_resource().Table(AUDIT_LOG_TABLE)
    for item in get_audit_trail(alert_id):
        table.delete_item(Key={"alert_id": alert_id, "timestamp": item["timestamp"]})
