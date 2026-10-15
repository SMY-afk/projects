from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from erp_api.services.sample_application_repository import (
    SampleApplicationRepository,
)
from erp_api.services.sample_application_upsert import SamplePayloadObservation


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeDatabase:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    @asynccontextmanager
    async def system_session_factory(self):
        yield self.session


def _observation(application_id: str) -> SamplePayloadObservation:
    return SamplePayloadObservation(
        payload={"id": application_id},
        observed_at=datetime(2026, 9, 10, tzinfo=UTC),
        request_id=f"request-{application_id}",
        source_capture_id=uuid4(),
    )


def test_batch_upsert_rolls_back_every_record_when_one_record_fails() -> None:
    session = FakeSession()
    repository = SampleApplicationRepository(FakeDatabase(session))  # type: ignore[arg-type]
    attempted: list[str] = []

    async def fake_upsert(_session, *, observation, **_kwargs):
        application_id = str(observation.payload["id"])
        attempted.append(application_id)
        if application_id == "sample-2":
            raise RuntimeError("write failed")
        return uuid4()

    repository._upsert_in_session = fake_upsert  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="write failed"):
        asyncio.run(
            repository.upsert_source_payloads(
                tenant_id=uuid4(),
                shop_id=uuid4(),
                observations=(_observation("sample-1"), _observation("sample-2")),
                source_type="official_api",
            )
        )

    assert attempted == ["sample-1", "sample-2"]
    assert session.commits == 0
    assert session.rollbacks == 1


def test_batch_upsert_commits_once_after_every_record_succeeds() -> None:
    session = FakeSession()
    repository = SampleApplicationRepository(FakeDatabase(session))  # type: ignore[arg-type]

    async def fake_upsert(_session, **_kwargs):
        return uuid4()

    repository._upsert_in_session = fake_upsert  # type: ignore[method-assign]
    result = asyncio.run(
        repository.upsert_source_payloads(
            tenant_id=uuid4(),
            shop_id=uuid4(),
            observations=(_observation("sample-1"), _observation("sample-2")),
            source_type="official_api",
        )
    )

    assert len(result) == 2
    assert session.commits == 1
    assert session.rollbacks == 0


def test_batch_upsert_processes_group_parent_after_single_item_members() -> None:
    session = FakeSession()
    repository = SampleApplicationRepository(FakeDatabase(session))  # type: ignore[arg-type]
    attempted: list[str] = []
    returned_ids = {"group-parent": uuid4(), "group-member": uuid4()}

    async def fake_upsert(_session, *, observation, **_kwargs):
        application_id = str(observation.payload["id"])
        attempted.append(application_id)
        return returned_ids[application_id]

    repository._upsert_in_session = fake_upsert  # type: ignore[method-assign]
    grouped = SamplePayloadObservation(
        payload={
            "id": "group-parent",
            "source_item_ids": ["group-member", "group-parent"],
        },
        observed_at=datetime(2026, 9, 10, tzinfo=UTC),
        request_id="request-group-parent",
        source_capture_id=uuid4(),
    )
    member = _observation("group-member")

    result = asyncio.run(
        repository.upsert_source_payloads(
            tenant_id=uuid4(),
            shop_id=uuid4(),
            observations=(grouped, member),
            source_type="hubstudio_cdp",
        )
    )

    assert attempted == ["group-member", "group-parent"]
    assert result == (returned_ids["group-parent"], returned_ids["group-member"])
