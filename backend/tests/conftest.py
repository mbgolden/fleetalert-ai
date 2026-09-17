import os
from collections.abc import Iterator

import pytest
from moto import mock_aws

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
