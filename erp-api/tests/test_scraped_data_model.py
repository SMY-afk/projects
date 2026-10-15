from sqlalchemy import JSON, BigInteger, ForeignKeyConstraint, UniqueConstraint

import erp_api.models
from erp_api.db.base import Base


def test_scraped_data_has_expected_raw_capture_columns() -> None:
    table = Base.metadata.tables["scraped_data"]

    assert list(table.columns.keys()) == [
        "id",
        "platform_id",
        "data_type",
        "creator_id",
        "creator_name",
        "title",
        "raw_data",
        "created_at",
        "updated_at",
        "tenant_id",
    ]
    assert isinstance(table.c.id.type, BigInteger)
    assert table.c.id.autoincrement is True
    assert type(table.c.raw_data.type) is JSON
    assert table.c.raw_data.nullable is False
    assert table.c.platform_id.nullable is False
    assert table.c.data_type.nullable is False


def test_scraped_data_platform_id_is_globally_unique() -> None:
    table = Base.metadata.tables["scraped_data"]
    unique_constraints = {
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    foreign_keys = {
        (
            tuple(constraint.column_keys),
            tuple(element.target_fullname for element in constraint.elements),
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }

    assert (
        "uq_scraped_data_platform_id",
        ("platform_id",),
    ) in unique_constraints
    assert (("tenant_id",), ("tenants.id",)) in foreign_keys
    assert {index.name for index in table.indexes} == {
        "ix_scraped_data_creator_id",
        "ix_scraped_data_data_type",
        "ix_scraped_data_tenant_id",
    }


def test_scraped_data_model_is_exported() -> None:
    assert erp_api.models.ScrapedData is not None
    assert "ScrapedData" in erp_api.models.__all__
