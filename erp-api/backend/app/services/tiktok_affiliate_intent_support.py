def intent_failure_category(category: str) -> str:
    if category in {"captcha", "session_expired", "http_403", "rate_limited"}:
        return category
    if category in {"payload_handler_failed", "payload_structure_changed"}:
        return "window_mismatch"
    return "request_timeout"


def is_intent_target(page, resource, target_page, target_resource) -> bool:
    return page is target_page and resource == target_resource
