"""DynamoDB table naming and resource access.

Table names here must match what infra/modules/dynamodb/main.tf provisions
in AWS (`${project_name}-${environment}-<suffix>`).
"""

from functools import cache
from typing import Any

import boto3

from fleetalert import config


def _table_name(suffix: str) -> str:
    return f"{config.PROJECT_NAME}-{config.environment()}-{suffix}"


MACHINES_TABLE = _table_name("machines")
TELEMETRY_TABLE = _table_name("telemetry")
ALERTS_TABLE = _table_name("alerts")
KNOWLEDGE_BASE_TABLE = _table_name("knowledge-base")
TRACES_TABLE = _table_name("traces")
USAGE_TABLE = _table_name("usage")
TRACES_ALERT_INDEX = "alert_id-span_id-index"


@cache
def get_dynamodb_resource() -> Any:
    """One resource per Lambda container, reused across calls and invocations.

    It used to be built on every call, so every DynamoDB request opened a
    fresh HTTPS connection. The first load test measured ~80 ms per call and
    2.3 s per model-free round (ADR-0023). Tests clear the cache between
    moto contexts.
    """
    return boto3.resource("dynamodb", region_name=config.aws_region())
