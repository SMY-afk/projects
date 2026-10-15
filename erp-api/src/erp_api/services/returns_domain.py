from dataclasses import dataclass
from uuid import UUID


class ReturnNotFoundError(ValueError):
    pass


class ReturnValidationError(ValueError):
    pass


class ReturnConflictError(ValueError):
    pass


@dataclass(frozen=True)
class ReturnItemInput:
    order_line_id: UUID
    requested_quantity: int
    reason_code: str
    note: str | None = None


def validate_return_items(items: list[ReturnItemInput]) -> None:
    if not items:
        raise ReturnValidationError("At least one return item is required.")
    if len({item.order_line_id for item in items}) != len(items):
        raise ReturnValidationError("An order line can appear only once.")
    if any(item.requested_quantity < 1 for item in items):
        raise ReturnValidationError("Requested quantity must be positive.")
