import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from erp_api.models.order import Order
from erp_api.services.order_sync_repository import OrderSyncRepository
from erp_api.services.tiktok_order_schemas import TikTokOrderAttributionSignal
from erp_api.services.token_cipher import TokenCipher


class FakeDatabase:
    def __init__(self, session):
        self._session = session

    async def session(self, tenant_id):
        yield self._session


class FakeSession:
    def __init__(self, tenant_id, scalar_values):
        self.info = {"tenant_id": tenant_id}
        self._scalar_values = list(scalar_values)
        self.added = []
        self.events = []
        self.commits = 0

    async def scalar(self, statement):
        return self._scalar_values.pop(0)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.events.append("flush")
        for value in self.added:
            if isinstance(value, Order) and value.id is None:
                value.id = uuid4()

    async def execute(self, statement):
        self.events.append("execute")
        return SimpleNamespace()

    async def commit(self):
        self.commits += 1
        self.events.append("commit")


class RecordingAttributionRepository:
    def __init__(self, events):
        self.events = events
        self.calls = []

    async def upsert(self, session, tenant_id, order_id, decision):
        self.events.append("attribution")
        self.calls.append((session, tenant_id, order_id, decision))


class RecordingOrderSyncRepository(OrderSyncRepository):
    def __init__(self, database, pii_cipher, events, logistics_projector=None):
        super().__init__(
            database,
            pii_cipher,
            logistics_projector=logistics_projector,
        )
        self.events = events

    async def _replace_children(self, session, tenant_id, shop_id, stored, incoming):
        self.events.append("children")


def _incoming(*, updated_at: datetime, sample: bool | None = None):
    return SimpleNamespace(
        platform_order_id="order-1",
        order_number="order-1",
        status="completed",
        external_status="COMPLETED",
        currency="USD",
        subtotal_amount_minor=100,
        shipping_fee_minor=0,
        discount_amount_minor=0,
        tax_amount_minor=0,
        total_amount_minor=100,
        buyer_username=None,
        placed_at=updated_at,
        paid_at=updated_at,
        platform_updated_at=updated_at,
        attribution_signal=TikTokOrderAttributionSignal(
            is_sample_order=sample,
            source_updated_at=updated_at,
        ),
    )


def _repository(session, events, logistics_projector=None):
    repository = RecordingOrderSyncRepository(
        FakeDatabase(session),
        TokenCipher("test-only-order-pii-encryption-key-32-chars"),
        events,
        logistics_projector,
    )
    repository._attribution_repository = RecordingAttributionRepository(events)
    return repository


def test_sync_writes_attribution_after_order_children_in_same_session() -> None:
    tenant_id = uuid4()
    run_id = uuid4()
    shop_id = uuid4()
    events = []
    session = FakeSession(tenant_id, [None, None])
    repository = _repository(session, events)

    applied = asyncio.run(
        repository.upsert_page(
            tenant_id,
            run_id,
            shop_id,
            [_incoming(updated_at=datetime(2026, 8, 13, tzinfo=UTC), sample=True)],
            "next",
        )
    )

    assert applied == 1
    assert events.index("children") < events.index("attribution")
    assert session.commits == 1
    attribution_session, attribution_tenant, order_id, decision = (
        repository._attribution_repository.calls[0]
    )
    assert attribution_session is session
    assert attribution_tenant == tenant_id
    assert order_id is not None
    assert decision.source_updated_at == datetime(2026, 8, 13, tzinfo=UTC)
    assert decision.special_order_type == "unknown"


def test_sync_projects_logistics_after_order_children_in_same_transaction() -> None:
    tenant_id = uuid4()
    run_id = uuid4()
    shop_id = uuid4()
    events = []
    projected = []

    async def project(session, projected_tenant_id, order_id):
        events.append("logistics")
        projected.append((session, projected_tenant_id, order_id))

    session = FakeSession(tenant_id, [None, None])
    repository = _repository(session, events, project)

    applied = asyncio.run(
        repository.upsert_page(
            tenant_id,
            run_id,
            shop_id,
            [_incoming(updated_at=datetime(2026, 8, 13, tzinfo=UTC))],
            "next",
        )
    )

    assert applied == 1
    assert events.index("children") < events.index("logistics")
    assert events.index("logistics") < session.events.index("commit")
    assert projected[0][0] is session
    assert projected[0][1] == tenant_id
    assert projected[0][2] is not None


def test_older_order_response_does_not_rewrite_attribution() -> None:
    tenant_id = uuid4()
    run_id = uuid4()
    shop_id = uuid4()
    events = []
    stored = Order(id=uuid4(), platform_updated_at=datetime(2026, 8, 13, tzinfo=UTC))
    session = FakeSession(tenant_id, [stored, None])
    repository = _repository(session, events)

    applied = asyncio.run(
        repository.upsert_page(
            tenant_id,
            run_id,
            shop_id,
            [_incoming(updated_at=datetime(2026, 8, 12, tzinfo=UTC), sample=False)],
            "next",
        )
    )

    assert applied == 0
    assert repository._attribution_repository.calls == []
    assert "children" not in events
    assert session.commits == 1


def test_missing_attribution_signal_still_writes_unknown_decision() -> None:
    tenant_id = uuid4()
    run_id = uuid4()
    shop_id = uuid4()
    events = []
    session = FakeSession(tenant_id, [None, None])
    repository = _repository(session, events)
    incoming = _incoming(updated_at=datetime(2026, 8, 13, tzinfo=UTC))
    incoming.attribution_signal = None

    applied = asyncio.run(
        repository.upsert_page(tenant_id, run_id, shop_id, [incoming], "next")
    )

    assert applied == 1
    assert (
        repository._attribution_repository.calls[0][3].classification_status
        == "unknown"
    )
