import os

import pytest

from tests.conftest import assert_not_production_database


def test_production_database_name_is_refused():
    with pytest.raises(RuntimeError, match="production database"):
        assert_not_production_database(
            "postgresql://admin:x@127.0.0.1:15432/job_machine"
        )


def test_test_database_name_is_allowed():
    assert_not_production_database(
        "postgresql://admin:x@127.0.0.1:15432/job_machine_test"
    ) is None
