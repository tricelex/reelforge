from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError


def pydantic_validator(schema: type[BaseModel]):
    """Return a Django field validator backed by a Pydantic model.

    Usage:
        field = models.JSONField(
            default=dict,
            validators=[pydantic_validator(MySchema)],
        )
    """

    def validate(value: Any) -> None:
        if value is None:
            return
        try:
            schema.model_validate(value)
        except PydanticValidationError as e:
            errors = [f"{' -> '.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in e.errors()]
            raise ValidationError(errors)

    validate.__name__ = f"validate_{schema.__name__}"
    return validate
