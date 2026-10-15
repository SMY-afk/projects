from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.sample_source_policy import SampleSourcePolicyRepository


@pytest.mark.asyncio
async def test_reconciliation_only_compares_free_batches_and_free_receipts():
    class Session:
        async def scalar(self, query):
            compiled = query.compile(dialect=postgresql.dialect())
            assert "sample_type" in str(compiled)
            assert "free" in compiled.params.values()
            return None

    assert await SampleSourcePolicyRepository._recovery_times(Session(), uuid4(), uuid4()) == (None, None)
