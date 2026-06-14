import uuid

from django.db import models

from server.common.models import TimeStampedModel, UUIDModel


class _SampleModel(UUIDModel, TimeStampedModel):
    name = models.CharField(max_length=10)

    class Meta:
        app_label = 'main'


def test_uuid_model_uses_uuid_primary_key() -> None:
    instance = _SampleModel(name='x')
    assert isinstance(instance.id, uuid.UUID)


def test_timestamped_model_has_created_at_field() -> None:
    assert hasattr(TimeStampedModel, 'created_at')


def test_timestamped_model_has_updated_at_field() -> None:
    assert hasattr(TimeStampedModel, 'updated_at')
