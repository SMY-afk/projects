class FeishuSampleError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str = "feishu_error",
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code[:64]
        self.request_id = request_id
