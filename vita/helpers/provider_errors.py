"""Provider failures relevant to structured-output negotiation (not backoff)."""


class ProviderError(RuntimeError):
    def __init__(self, message: str, code: str = "provider_error", status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


class UnsupportedSchema(ProviderError):
    def __init__(self):
        super().__init__("This endpoint does not support schema-constrained output.", "unsupported_schema")
