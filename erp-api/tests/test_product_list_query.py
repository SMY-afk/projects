from uuid import uuid4

from sqlalchemy.dialects import postgresql

from erp_api.services.product_repository import ProductRepository


def test_product_list_query_filters_before_pagination() -> None:
    statement = ProductRepository._product_list_statement(
        tenant_id=uuid4(),
        keyword="drift car",
        status="ACTIVATE",
        page=2,
        page_size=10,
    )

    compiled = statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    sql = str(compiled)

    assert "products.name ILIKE '%%drift car%%'" in sql
    assert "products.code ILIKE '%%drift car%%'" in sql
    assert "products.platform_product_id ILIKE '%%drift car%%'" in sql
    assert "EXISTS" in sql
    assert "products.status = 'ACTIVATE'" in sql
    assert "LIMIT 10 OFFSET 10" in sql


def test_product_count_query_uses_the_same_filters_without_pagination() -> None:
    statement = ProductRepository._product_count_statement(
        tenant_id=uuid4(),
        keyword="A-ST",
        status="DRAFT",
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "count(*)" in sql
    assert "products.status = 'DRAFT'" in sql
    assert "LIMIT" not in sql
    assert "OFFSET" not in sql
