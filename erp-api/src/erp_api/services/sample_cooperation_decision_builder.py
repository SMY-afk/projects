"""Build an auditable cooperation decision from the matched source rows."""


def decision_for_rows(candidate, event_type, reason, matches, *,
                      recent_date=None, recipients=()):
    from erp_api.services.sample_cooperation_rules import CooperationDecision

    return CooperationDecision(
        candidate=candidate, event_type=event_type, reason=reason,
        matched_count=len(matches), recent_date=recent_date,
        sources=tuple(sorted({row.source for row in matches})), recipients=recipients,
    )
