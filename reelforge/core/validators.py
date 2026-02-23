from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError


class PydanticValidator:
    """A Django field validator backed by a Pydantic model.

    Implemented as a class (not a closure) so Django's migration writer can
    serialize it via deconstruct(). Closures returned by factory functions
    cannot be found by the serializer and cause ValueError at makemigrations time.

    Usage:
        field = models.JSONField(
            default=dict,
            validators=[pydantic_validator(MySchema)],
        )
    """

    def __init__(self, schema: type[BaseModel]) -> None:
        self.schema = schema

    def __call__(self, value: Any) -> None:
        if value is None:
            return
        try:
            self.schema.model_validate(value)
        except PydanticValidationError as e:
            errors = [
                f"{' -> '.join(str(loc) for loc in err['loc'])}: {err['msg']}"
                for err in e.errors()
            ]
            raise ValidationError(errors)

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        path = f"{self.__class__.__module__}.{self.__class__.__qualname__}"
        return path, [self.schema], {}

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PydanticValidator):
            return self.schema == other.schema
        return NotImplemented

    def __repr__(self) -> str:
        return f"PydanticValidator({self.schema.__name__})"


def pydantic_validator(schema: type[BaseModel]) -> PydanticValidator:
    """Return a Django field validator backed by a Pydantic model."""
    return PydanticValidator(schema)
