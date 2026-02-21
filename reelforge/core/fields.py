from __future__ import annotations

import json
from typing import Any
from typing import TypeVar

from django.db import models
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class PydanticField(models.JSONField):
    """A JSONField that automatically serializes/deserializes Pydantic models.

    Stores the model as JSON in the database and rehydrates it as a Pydantic
    instance on read. Useful for structured agent output stored alongside a job.

    Usage:
        class ScriptJob(PipelineStageModel):
            script_output = PydanticField(schema=ScriptAgentOutput, null=True, blank=True)
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
        raw = super().to_python(value)
        if isinstance(raw, (dict, list)):
            return self.schema.model_validate(raw)
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
