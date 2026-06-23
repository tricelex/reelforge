import pytest

from server.apps.channels.models import Channel, ChannelKind
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
)
from server.apps.publishing.models import PublishJob, PublishStatus


@pytest.fixture
def channel(db):
    return Channel.objects.create(
        name='Test Channel',
        kind=ChannelKind.LONGFORM,
    )


@pytest.fixture
def blueprint(db):
    return PipelineBlueprint.objects.create(
        name='pub_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )


@pytest.fixture
def run(channel, blueprint):
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic='Test topic',
    )


@pytest.mark.django_db
def test_publish_job_default_status(run, channel):
    job = PublishJob.objects.create(run=run, channel=channel)
    assert job.status == PublishStatus.PENDING


@pytest.mark.django_db
def test_publish_job_str(run, channel):
    job = PublishJob.objects.create(run=run, channel=channel)
    assert 'PENDING' in str(job)
    assert str(job.id) in str(job)


def test_publish_status_values():
    assert set(PublishStatus.values) == {
        'PENDING',
        'UPLOADING',
        'COMPLETED',
        'FAILED',
    }
