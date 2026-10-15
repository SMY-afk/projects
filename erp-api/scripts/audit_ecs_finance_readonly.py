"""Summarize production finance runs and cursors without modifying RDS."""

import asyncio
import json

from sqlalchemy import text

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database


async def main() -> None:
    database = Database(get_settings().database_url)
    try:
        async with database.system_session_factory() as session:
            totals = (
                await session.execute(
                    text(
                        "SELECT status, count(*) AS n FROM finance_sync_runs "
                        "GROUP BY status ORDER BY status"
                    )
                )
            ).all()
            print("RUN_TOTALS=" + ",".join(f"{row.status}:{row.n}" for row in totals))
            recent = (
                await session.execute(
                    text(
                        "SELECT status, count(*) AS n FROM finance_sync_runs "
                        "WHERE started_at >= now() - interval '1 hour' "
                        "GROUP BY status ORDER BY status"
                    )
                )
            ).all()
            print("RECENT_RUNS=" + ",".join(f"{row.status}:{row.n}" for row in recent))
            rows = (
                await session.execute(
                    text(
                        "SELECT s.shop_name, r.status, r.error_code, "
                        "r.started_at, r.finished_at, r.window_from, r.window_to, "
                        "r.fetched_count, r.written_count "
                        "FROM finance_sync_runs r JOIN shops s ON s.id=r.shop_id "
                        "WHERE r.started_at >= now() - interval '3 hours' "
                        "ORDER BY r.started_at DESC LIMIT 30"
                    )
                )
            ).all()
            for row in rows:
                print(
                    f"RUN={row.shop_name}|{row.status}|{row.error_code or '-'}|"
                    f"{row.started_at.isoformat()}|"
                    f"{row.finished_at.isoformat() if row.finished_at else '-'}|"
                    f"span_hours={(row.window_to-row.window_from).total_seconds()/3600:.1f}|"
                    f"fetched={row.fetched_count}|written={row.written_count}"
                )
            cursors = (
                await session.execute(
                    text(
                        "SELECT s.shop_name, c.entity_type, c.last_successful_at "
                        "FROM finance_sync_cursors c JOIN shops s ON s.id=c.shop_id "
                        "WHERE c.entity_type='finance' ORDER BY s.shop_name"
                    )
                )
            ).all()
            for row in cursors:
                print(
                    f"CURSOR={row.shop_name}|{row.entity_type}|"
                    f"{row.last_successful_at.isoformat() if row.last_successful_at else '-'}"
                )
            progress = (
                await session.execute(
                    text(
                        "SELECT s.shop_name, r.window_from, r.window_to, "
                        "(SELECT count(*) FROM finance_statements st "
                        " WHERE st.shop_id=s.id AND st.statement_end_at>=r.window_from "
                        " AND st.statement_end_at<r.window_to) AS statement_total, "
                        "c.recovery_cursor "
                        "FROM shops s JOIN LATERAL "
                        "(SELECT window_from, window_to FROM finance_sync_runs "
                        " WHERE shop_id=s.id ORDER BY started_at DESC LIMIT 1) r ON true "
                        "LEFT JOIN finance_sync_cursors c ON c.shop_id=s.id "
                        " AND c.entity_type='statement_transactions' "
                        "WHERE s.shop_name IN ('Akeleo Toys','fanfu toy tool')"
                    )
                )
            ).all()
            for row in progress:
                try:
                    state = json.loads(row.recovery_cursor or "{}")
                except (TypeError, ValueError):
                    state = {}
                same_window = (
                    state.get("window_from") == row.window_from.isoformat()
                    and state.get("window_to") == row.window_to.isoformat()
                )
                current_id = state.get("statement_id") if same_window else None
                position = None
                if current_id:
                    position = (
                        await session.execute(
                            text(
                                "SELECT count(*) FROM finance_statements st "
                                "WHERE st.shop_id=(SELECT id FROM shops WHERE shop_name=:shop) "
                                "AND st.statement_end_at>=:start "
                                "AND st.statement_end_at<:end "
                                "AND (st.statement_end_at, st.id) <= "
                                "(SELECT st2.statement_end_at, st2.id "
                                " FROM finance_statements st2 "
                                " WHERE st2.shop_id=st.shop_id "
                                " AND st2.platform_statement_id=:statement_id)"
                            ),
                            {
                                "shop": row.shop_name,
                                "start": row.window_from,
                                "end": row.window_to,
                                "statement_id": current_id,
                            },
                        )
                    ).scalar_one()
                print(
                    f"STATEMENT_PROGRESS={row.shop_name}|TOTAL={row.statement_total}|"
                    f"POSITION={position if position is not None else '-'}|"
                    f"SAME_WINDOW={same_window}|DONE={state.get('done', False)}|"
                    f"PAGE_PENDING={bool(state.get('page_token'))}"
                )
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
