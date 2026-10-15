from scripts.repair_feishu_bd_invitation_batch import (
    ExistingRow,
    build_repair_groups,
)


def _row(number: int, creator_id: str) -> ExistingRow:
    return ExistingRow(
        f"rec-{number}",
        number,
        creator_id,
        "example-2b3220d55335",
        "example-2b3220d55335",
        {"自动编号": str(number), "达人ID": creator_id},
    )


def test_build_repair_groups_merges_spaces_and_allows_small_corrections() -> None:
    rows = (
        _row(231, "nikasteward777"),
        _row(232, "jay"),
        _row(233, "alonso"),
        _row(234, "hjacks39"),
        _row(235, "momma"),
        _row(236, "t"),
        _row(237, "75"),
    )

    groups = build_repair_groups(
        rows,
        ("nikasteward777", "jayalonso", "bjacks39", "momma t 75"),
    )

    assert tuple(group.keep_auto_number for group in groups) == (231, 232, 234, 235)
    assert groups[1].delete_auto_numbers == (233,)
    assert groups[2].edit_distance == 1
    assert groups[3].delete_auto_numbers == (236, 237)
