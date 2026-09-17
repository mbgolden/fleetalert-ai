"""DynamoDB table naming and resource access.

Table names here must match what infra/modules/dynamodb/main.tf provisions
in AWS (`${project_name}-${environment}-<suffix>`).
"""

import os
from typing import Any

import boto3

PROJECT_NAME = "fleetalert-ai"
ENVIRONMENT = os.environ.get("FLEETALERT_ENV", "demo")


def _table_name(suffix: str) -> str:
    return f"{PROJECT_NAME}-{ENVIRONMENT}-{suffix}"


MACHINES_TABLE = _table_name("machines")
TELEMETRY_TABLE = _table_name("telemetry")
ALERTS_TABLE = _table_name("alerts")
KNOWLEDGE_BASE_TABLE = _table_name("knowledge-base")
AUDIT_LOG_TABLE = _table_name("audit-log")


def get_dynamodb_resource() -> Any:
    return boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
