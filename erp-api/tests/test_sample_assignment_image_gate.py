from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.sample_assignment_image_gate import (
    SampleAssignmentImageGate,
    _source_image_urls,
)
from erp_api.services.sample_auto_assignment_service import (
    SampleAssignmentItemResult,
    SampleAutoAssignmentRunResult,
)
from erp_api.services.sample_shop_pipeline_service import SampleShopPipelineService


class Session:
    def __init__(self, application):
        self.application = application

    async def scalar(self, _statement):
        return self.application


class Database:
    def __init__(self, application):
        self.application = application

    @asynccontextmanager
    async def system_session_factory(self):
        yield Session(self.application)


class Verifier:
    def __init__(self, unavailable=()):
        self.unavailable = set(unavailable)
        self.checked = []

    async def is_available(self, source_url):
        self.checked.append(source_url)
        return source_url not in self.unavailable


def application(*, products, stored=None):
    return SimpleNamespace(
        raw_payload={"products": [{"product": item} for item in products]},
        product_image_urls=stored or [],
        sku_image_url=None,
    )


@pytest.mark.asyncio
async def test_missing_source_image_blocks_even_if_stored_image_is_present():
    sample = application(products=[{"sku_image_url": None}], stored=["old-image"])
    verifier = Verifier()
    gate = SampleAssignmentImageGate(Database(sample), verifier)

    reason = await gate.blocked_reason(uuid4(), uuid4(), uuid4())

    assert reason == "sample_image_missing"
    assert verifier.checked == []


@pytest.mark.asyncio
async def test_unavailable_image_blocks_allocation():
    sample = application(products=[{"sku_image_url": "image-one"}])
    verifier = Verifier(unavailable={"image-one"})
    gate = SampleAssignmentImageGate(Database(sample), verifier)

    reason = await gate.blocked_reason(uuid4(), uuid4(), uuid4())

    assert reason == "sample_image_unavailable"
    assert verifier.checked == ["image-one"]


@pytest.mark.asyncio
async def test_all_products_need_a_reachable_image():
    sample = application(
        products=[{"sku_image_url": "image-one"}, {"sku_image_url": "image-two"}]
    )
    verifier = Verifier()
    gate = SampleAssignmentImageGate(Database(sample), verifier)

    assert await gate.blocked_reason(uuid4(), uuid4(), uuid4()) is None
    assert verifier.checked == ["image-one", "image-two"]


def test_missing_image_in_one_product_cannot_be_hidden_by_another_product():
    sample = application(
        products=[{"sku_image_url": "image-one"}, {"sku_image_url": ""}]
    )

    assert _source_image_urls(sample) == ()


@pytest.mark.asyncio
async def test_sample_row_is_synced_before_image_block_and_no_bd_record_is_created():
    calls = []
    application_id = uuid4()

    class FeishuSync:
        async def sync(self, **_kwargs):
            calls.append("sample_row")
            return SimpleNamespace(status="succeeded")

    class Assignments:
        async def run_for_shop(self, **_kwargs):
            calls.append("allocation")
            return SampleAutoAssignmentRunResult(
                status="succeeded",
                items=(
                    SampleAssignmentItemResult(
                        application_id=application_id,
                        status="blocked",
                        blocked_reason="sample_image_missing",
                    ),
                ),
            )

    class Projection:
        async def sync(self, **_kwargs):
            return None

    class AssignmentRecords:
        async def sync(self, *, application_ids, **_kwargs):
            assert application_ids == frozenset()
            calls.append("assignment_records")

    class ProfileEnrichment:
        async def enrich(self, **_kwargs):
            return None

    pipeline = SampleShopPipelineService(
        None,
        FeishuSync(),
        auto_assignments=Assignments(),
        auto_assignment_projection=Projection(),
        assignment_records=AssignmentRecords(),
        profile_enrichment=ProfileEnrichment(),
    )

    result = await pipeline.complete_after_source(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        source_type="official_api",
        source_results=(
            SimpleNamespace(application_ids=frozenset({application_id})),
        ),
    )

    assert result.auto_assignment_result.blocked_count == 1
    assert calls == ["sample_row", "allocation", "assignment_records", "sample_row"]
