from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.logistics_repository import LogisticsTaskValidationError
from erp_api.services.logistics_workflow_repository import (
    ReviewItemInput,
    _differences,
    _review_result,
)


def _task_item(*, planned_quantity: int = 2):
    return SimpleNamespace(
        id=uuid4(),
        planned_quantity=planned_quantity,
        seller_sku="SKU-1",
    )


def test_matching_review_has_no_difference_and_passes() -> None:
    task_item = _task_item()
    items = {task_item.id: task_item}
    review_items = {
        task_item.id: ReviewItemInput(task_item.id, 2, None),
    }

    differences = _differences(items, review_items)

    assert differences == []
    assert _review_result(differences) == "passed"


def test_quantity_difference_records_reason_and_signed_quantity() -> None:
    task_item = _task_item()
    differences = _differences(
        {task_item.id: task_item},
        {task_item.id: ReviewItemInput(task_item.id, 1, "shortage")},
    )

    assert differences[0]["expectedQuantity"] == 2
    assert differences[0]["actualQuantity"] == 1
    assert differences[0]["differenceQuantity"] == -1
    assert differences[0]["reason"] == "shortage"
    assert _review_result(differences) == "quantity_mismatch"


def test_damaged_difference_uses_damaged_result() -> None:
    task_item = _task_item()
    differences = _differences(
        {task_item.id: task_item},
        {task_item.id: ReviewItemInput(task_item.id, 1, "damaged")},
    )

    assert _review_result(differences) == "damaged"


@pytest.mark.parametrize(
    ("actual_quantity", "reason"),
    [(1, None), (2, "other")],
)
def test_difference_reason_must_match_quantity_difference(
    actual_quantity: int, reason: str | None
) -> None:
    task_item = _task_item()

    with pytest.raises(LogisticsTaskValidationError):
        _differences(
            {task_item.id: task_item},
            {task_item.id: ReviewItemInput(task_item.id, actual_quantity, reason)},
        )
