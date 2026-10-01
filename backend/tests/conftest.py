import os
from collections.abc import Iterator

import pytest
from moto import mock_aws

from fleetalert import db, workflow
from fleetalert.repositories import create_tables

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")


@pytest.fixture
def dynamodb_tables() -> Iterator[None]:
    with mock_aws():
        create_tables()
        yield


@pytest.fixture(autouse=True)
def fresh_aws_clients() -> Iterator[None]:
    """AWS clients are cached per process (one per Lambda container); each
    test gets fresh ones so a moto context or a patched boto3 never leaks."""
    db.get_dynamodb_resource.cache_clear()
    workflow._stepfunctions.cache_clear()
    workflow._sqs.cache_clear()
    yield
    db.get_dynamodb_resource.cache_clear()
    workflow._stepfunctions.cache_clear()
    workflow._sqs.cache_clear()
