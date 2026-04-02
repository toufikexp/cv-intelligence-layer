from __future__ import annotations


class CVLayerError(Exception):
    """Base exception for CV Intelligence Layer."""

    def __init__(self, message: str, code: str = "CV_LAYER_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


class FileValidationError(CVLayerError):
    """Raised when an uploaded file fails validation."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="FILE_VALIDATION_ERROR")


class EntityExtractionError(CVLayerError):
    """Raised when entity extraction fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="ENTITY_EXTRACTION_ERROR")


class SearchClientError(CVLayerError):
    """Raised when Semantic Search API calls fail."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="SEARCH_CLIENT_ERROR")


class LLMClientError(CVLayerError):
    """Raised when LLM API calls fail."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="LLM_CLIENT_ERROR")


class PipelineError(CVLayerError):
    """Raised when a pipeline stage fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="PIPELINE_ERROR")
