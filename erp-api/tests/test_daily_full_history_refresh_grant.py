import pytest

from erp_api.workers import daily_valid_creator_jobs as jobs


class Redis:
    def __init__(self, values):
        self.values = values

    async def get(self, key):
        return self.values.get(key)


def test_attempt_budget_removed_without_changing_business_rule_version():
    assert not hasattr(jobs, "_attempt_limit")
    assert not hasattr(jobs, "MAX_SYNC_ATTEMPTS_PER_BATCH")
    assert jobs.SYNC_RULE_VERSION == "sample-approval-full-history-reconciliation-v5"


@pytest.mark.asyncio
async def test_excluded_accounts_normalized_and_validated():
    redis = Redis({jobs.EXCLUDED_ACCOUNTS_KEY: '[" @YANA_OK1 "]'})
    assert await jobs._excluded_accounts(redis) == frozenset({"yana_ok1"})
    for invalid in ('{}', '1', '[""]', 'null'):
        redis.values[jobs.EXCLUDED_ACCOUNTS_KEY] = invalid
        with pytest.raises(ValueError, match="exclusion"):
            await jobs._excluded_accounts(redis)


@pytest.mark.asyncio
async def test_no_exclusion_configuration_keeps_default_empty():
    assert await jobs._excluded_accounts(Redis({})) == frozenset()
