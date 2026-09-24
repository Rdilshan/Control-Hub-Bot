"""Unit tests for domain application exceptions."""

from app.exceptions import (
    ApplicationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)


def test_exception_properties():
    err = ValidationError("Field required", details={"field": "token"})
    assert err.code == "VALIDATION_ERROR"
    assert err.status_code == 422
    assert err.details == {"field": "token"}

    not_found = NotFoundError("Bot not found")
    assert not_found.code == "NOT_FOUND"
    assert not_found.status_code == 404

    conflict = ConflictError("Bot already connected")
    assert conflict.code == "CONFLICT"
    assert conflict.status_code == 409
