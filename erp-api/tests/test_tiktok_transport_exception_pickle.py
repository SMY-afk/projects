import pickle

from erp_api.services.tiktok_transport import TikTokApiError


def test_tiktok_api_error_can_be_deserialized_from_worker_result() -> None:
    original = TikTokApiError(
        "TikTok API rejected the request.",
        code="429",
        status_code=502,
        request_id="request-1",
    )

    restored = pickle.loads(pickle.dumps(original))

    assert str(restored) == str(original)
