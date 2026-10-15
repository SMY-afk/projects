class IntentPageError(RuntimeError):
    def __init__(self, category: str, *, page=None) -> None:
        super().__init__(category)
        self.category = category
        self.page = page
