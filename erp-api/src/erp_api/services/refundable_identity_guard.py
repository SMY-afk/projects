"""Quarantine unknown @accounts without discarding source applications."""

from sqlalchemy import and_, func, or_

QUARANTINE_KEY = "refundable_identity_quarantine"
QUARANTINE_REASON = "creator_unique_username_invalid"


def valid_unique_username(value):
    return (isinstance(value, str) and bool(value.strip().lstrip("@"))
            and not any(char.isspace() for char in value.strip().lstrip("@")))


def quarantined_payload(payload):
    if not isinstance(payload, dict):
        return False
    if payload.get(QUARANTINE_KEY) is not None:
        return True
    creator = payload.get("creator")
    return isinstance(creator, dict) and not valid_unique_username(creator.get("username"))


def refundable_identity_condition(model):
    return or_(model.sample_type != "refundable", and_(
        model.raw_payload[QUARANTINE_KEY].as_string().is_(None),
        model.creator_open_id.is_not(None),
        func.length(func.trim(model.creator_open_id)) > 0,
        model.creator_username.is_not(None),
        func.length(func.ltrim(func.trim(model.creator_username), "@")) > 0,
        ~func.trim(model.creator_username).op("~")(r"\s"),
    ))
