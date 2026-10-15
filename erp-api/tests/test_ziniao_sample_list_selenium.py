import json

from backend.app.services.ziniao_sample_list_selenium import (
    capture_ziniao_sample_list,
)


def _entry(method: str, params: dict[str, object]) -> dict[str, str]:
    return {"message": json.dumps({"message": {"method": method, "params": params}})}


class Driver:
    current_url = (
        "https://affiliate-us.tiktok.com/affiliate/sample/sample-request?shop_id=shop-1"
    )

    def __init__(self) -> None:
        self.cdp_calls = []
        self.script_calls = []
        self.refresh_calls = 0
        url = "https://affiliate-us.tiktok.com/api/v1/affiliate/sample/group/list"
        self.logs = [
            [],
            [
                _entry(
                    "Network.requestWillBeSent",
                    {
                        "requestId": "request-1",
                        "request": {
                            "url": url,
                            "method": "POST",
                            "postData": json.dumps(
                                {
                                    "tab": 10,
                                    "search_params": [],
                                    "order_params": [],
                                }
                            ),
                        },
                    },
                ),
                _entry(
                    "Network.responseReceived",
                    {
                        "requestId": "request-1",
                        "response": {
                            "url": url,
                            "status": 200,
                            "mimeType": "application/json",
                        },
                    },
                ),
                _entry("Network.loadingFinished", {"requestId": "request-1"}),
            ],
        ]
        self.payload = {
            "agg_info": [
                {
                    "apply_deatil": {
                        "creator_info": {"creator_id": "creator-1"},
                        "apply_infos": [
                            {
                                "apply_id": "application-1",
                                "product_id": "product-1",
                                "curr_status": 10,
                                "create_time": "1789088309846",
                            }
                        ],
                    }
                }
            ],
            "has_more": False,
        }

    def execute_cdp_cmd(self, method, _params):
        self.cdp_calls.append((method, _params))
        if method == "Network.getResponseBody":
            return {"body": json.dumps(self.payload), "base64Encoded": False}
        return {}

    def get_log(self, _kind):
        return self.logs.pop(0) if self.logs else []

    def execute_script(self, script, *arguments):
        self.script_calls.append((script, arguments))
        return True

    def refresh(self):
        self.refresh_calls += 1


def test_capture_reads_create_time_from_review_request_date_response() -> None:
    driver = Driver()

    capture = capture_ziniao_sample_list(driver, "shop-1", timeout_seconds=1)

    application = capture.page.applications[0]
    assert capture.observed_request_id == "request-1"
    assert application["products"][0]["application_id"] == "application-1"
    assert application["products"][0]["application_time"] == 1789088309
    assert ("Page.reload", {"ignoreCache": True}) in driver.cdp_calls
    assert driver.refresh_calls == 0
    assert [call[1][0] for call in driver.script_calls] == [
        ["To review"],
        ["Relevancy"],
        ["Request date"],
    ]
