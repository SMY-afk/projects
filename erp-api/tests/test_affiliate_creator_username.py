from erp_api.services.affiliate_metric_parse_support import (
    creator_username_aliases,
    creator_username_key,
)


def test_creator_username_key_ignores_at_prefix_and_case() -> None:
    assert creator_username_key("  @Retired_Welder_ ") == "retired_welder_"
    assert creator_username_aliases("@Retired_Welder_") == {
        "retired_welder_",
        "@retired_welder_",
    }
