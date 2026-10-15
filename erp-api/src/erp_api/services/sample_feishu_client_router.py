from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID


class SampleFeishuClientRouter:
    """Resolve one isolated Feishu table client for each ERP shop."""

    def __init__(self, default_client, clients_by_shop: Mapping[UUID, object]) -> None:
        self._default = default_client
        self._by_shop = dict(clients_by_shop)

    def for_shop(self, shop_id: UUID):
        client = self._by_shop.get(shop_id, self._default)
        if client is None:
            raise LookupError(
                f"Feishu sample table is not configured for shop {shop_id}."
            )
        return client

    def all_clients(self) -> tuple[object, ...]:
        clients: list[object] = []
        seen: set[int] = set()
        for client in (self._default, *self._by_shop.values()):
            if client is None or id(client) in seen:
                continue
            seen.add(id(client))
            clients.append(client)
        return tuple(clients)

    async def validate_required_fields(self) -> None:
        for client in self.all_clients():
            await client.validate_required_fields()
