"""Substrate exception hierarchy (adopted from polaris core)."""

from typing import Any, Dict, Optional


class AppError(Exception):
    """Base exception for all errors."""

    code: str = "APP_ERROR"

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class HttpError(AppError):
    """HTTP request failed."""

    code = "HTTP_ERROR"

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, details)
        self.status_code = status_code

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        if self.status_code is not None:
            result["status_code"] = self.status_code
        return result


class ConfigurationError(AppError):
    """Invalid or missing configuration."""

    code = "CONFIG_ERROR"


class ProviderError(AppError):
    """Error loading or using API providers."""

    code = "PROVIDER_ERROR"


class ApiCallError(AppError):
    """Error calling an API operation."""

    code = "API_CALL_ERROR"


class CapabilityError(AppError):
    """Operation requires a capability the manifest has not granted."""

    code = "CAPABILITY_DENIED"
