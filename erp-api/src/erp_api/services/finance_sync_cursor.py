from __future__ import annotations

import json
from datetime import datetime

from erp_api.services.finance_sync_repository import FinanceStoredCursor


def resume(
    cursor: FinanceStoredCursor, start: datetime, end: datetime
) -> tuple[str | None, bool]:
    state = cursor_state(cursor, start, end)
    return state.get("page_token") or None, bool(state.get("done"))


def cursor_state(cursor: FinanceStoredCursor, start: datetime, end: datetime) -> dict:
    if not cursor.recovery_cursor:
        return {}
    try:
        state = json.loads(cursor.recovery_cursor)
    except (TypeError, ValueError):
        return {}
    if (
        state.get("window_from") != start.isoformat()
        or state.get("window_to") != end.isoformat()
    ):
        return {}
    return state


def window_cursor(start: datetime, end: datetime, page_token: str) -> str:
    return json.dumps(
        {
            "window_from": start.isoformat(),
            "window_to": end.isoformat(),
            "page_token": page_token,
            "done": not bool(page_token),
        },
        sort_keys=True,
    )


def transaction_cursor(
    start: datetime,
    end: datetime,
    statement_id: str,
    page_token: str,
    *,
    done: bool,
) -> str:
    return json.dumps(
        {
            "window_from": start.isoformat(),
            "window_to": end.isoformat(),
            "statement_id": statement_id,
            "completed_statement_id": statement_id if not page_token else None,
            "page_token": page_token,
            "done": done,
        },
        sort_keys=True,
    )


def next_token(token: str, seen: set[str]) -> str:
    if token in seen:
        raise RuntimeError("TikTok Finance returned a repeated page token.")
    seen.add(token)
    return token
