import importlib
import warnings

from pydantic.warnings import UnsupportedFieldAttributeWarning

from erp_api.routers import data_schemas, finance_schemas


def test_api_schema_aliases_do_not_emit_unsupported_field_warnings() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", UnsupportedFieldAttributeWarning)
        importlib.reload(data_schemas)
        importlib.reload(finance_schemas)


def test_admin_resync_request_preserves_camel_case_contract() -> None:
    aliases = {
        name: field.alias
        for name, field in data_schemas.AdminResyncRequest.model_fields.items()
    }

    assert aliases == {
        "shop_id": "shopId",
        "resource_types": "resourceTypes",
        "window_start": "windowStart",
        "window_end": "windowEnd",
        "currency": "currency",
        "account_type": "accountType",
    }
