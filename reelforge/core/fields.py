from __future__ import annotations

import json
from typing import Any
from typing import TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class PydanticField(models.JSONField):
    """DEPRECATED — Do not use for new fields.

    Use models.JSONField(default=dict/list, validators=[pydantic_validator(Schema)])
    from ***REMOVED***.core.validators instead.

    This class is kept solely so that historical 0002 migrations remain loadable
    (e.g. for showmigrations, squashmigrations). It must not be removed until all
    0002 migrations are either squashed into initial migrations or dropped entirely.
    """

    def __init__(self, schema: type[T], *args: Any, **kwargs: Any) -> None:
        self.schema = schema
        super().__init__(*args, **kwargs)

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        kwargs["schema"] = self.schema
        return name, path, args, kwargs

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> T | None:
        if value is None:
            return None
        raw = super().from_db_value(value, expression, connection)
        if isinstance(raw, (dict, list)):
            return self.schema.model_validate(raw)
        return None

    def to_python(self, value: Any) -> T | dict[str, Any] | None:
        if value is None:
            return None
        if isinstance(value, self.schema):
            return value
        # Django 5.2's JSONField does not define to_python() — it inherits
        # Field.to_python() which returns the value as-is without parsing JSON
        # strings. We must handle the string case explicitly.
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                msg = "Value must be valid JSON."
                raise ValidationError(msg) from exc
        if isinstance(value, (dict, list)):
            return self.schema.model_validate(value)
        return None

    def get_prep_value(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, BaseModel):
            return json.dumps(value.model_dump())
        if isinstance(value, (dict, list)):
            validated = self.schema.model_validate(value)
            return json.dumps(validated.model_dump())
        return super().get_prep_value(value)

    def value_from_object(self, obj: Any) -> dict[str, Any] | None:
        value = getattr(obj, self.attname)
        if isinstance(value, BaseModel):
            return value.model_dump()
        return value

    def formfield(self, **kwargs: Any) -> Any:
        class PydanticEncoder(json.JSONEncoder):
            def default(self, obj: Any) -> Any:
                if isinstance(obj, BaseModel):
                    return obj.model_dump()
                return super().default(obj)

        kwargs.setdefault("encoder", PydanticEncoder)
        return super().formfield(**kwargs)
