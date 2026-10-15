from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, case, func, or_
from sqlalchemy.dialects.postgresql import array, insert

CONTENT_UPSERT_BATCH_SIZE = 300


def content_batches(rows: list[dict[str, object]]):
    for index in range(0, len(rows), CONTENT_UPSERT_BATCH_SIZE):
        yield rows[index : index + CONTENT_UPSERT_BATCH_SIZE]


def content_upsert_statement(
    model,
    rows: list[dict[str, object]],
    *,
    constraint: str,
    preserve_existing_details: bool,
):
    statement = insert(model).values(rows)
    source_is_newer = or_(
        model.source_updated_at.is_(None),
        statement.excluded.source_updated_at.is_not(None)
        & (model.source_updated_at <= statement.excluded.source_updated_at),
    )
    existing_products = model.fields["promotedProducts"].astext
    has_rich_details = or_(
        func.nullif(model.fields["coverImageUrl"].astext, "").is_not(None),
        func.nullif(model.fields["creatorAvatarUrl"].astext, "").is_not(None),
        and_(
            existing_products.is_not(None),
            existing_products.notin_(("[]", "null")),
        ),
    )
    incoming_username = statement.excluded.fields["creatorUsername"]
    incoming_nickname = statement.excluded.fields["creatorNickname"]
    identity_updated_fields = case(
        (
            func.nullif(incoming_username.astext, "").is_not(None),
            func.jsonb_set(
                model.fields,
                array(["creatorUsername"]),
                incoming_username,
                True,
            ),
        ),
        else_=model.fields,
    )
    identity_updated_fields = case(
        (
            func.nullif(incoming_nickname.astext, "").is_not(None),
            func.jsonb_set(
                identity_updated_fields,
                array(["creatorNickname"]),
                incoming_nickname,
                True,
            ),
        ),
        else_=identity_updated_fields,
    )
    updated_fields = (
        case(
            (has_rich_details, identity_updated_fields),
            else_=statement.excluded.fields,
        )
        if preserve_existing_details
        else statement.excluded.fields
    )
    return statement.on_conflict_do_update(
        constraint=constraint,
        set_={
            "fields": updated_fields,
            "source_status": statement.excluded.source_status,
            "status": statement.excluded.status,
            "source_updated_at": statement.excluded.source_updated_at,
            "platform_request_id": statement.excluded.platform_request_id,
            "observed_at": datetime.now(UTC),
        },
        where=source_is_newer,
    )
