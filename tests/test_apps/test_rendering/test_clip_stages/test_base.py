"""Tests for RenderStage ABC and RenderStageError."""

from pathlib import Path

from server.apps.rendering.clip_stages.base import RenderStage, RenderStageError


class _ConcreteStage(RenderStage):
    @property
    def name(self) -> str:
        return 'test'

    @property
    def order(self) -> int:
        return 1

    def run(self, input_path: Path) -> Path:
        return input_path


def test_should_run_default() -> None:
    stage = _ConcreteStage()
    assert stage.should_run() is True
    assert stage.name == 'test'
    assert stage.order == 1
    assert stage.run(Path('/input.mp4')) == Path('/input.mp4')


def test_render_stage_error_message() -> None:
    cause = ValueError('bad input')
    err = RenderStageError('trim_and_crop', 1, cause)
    assert 'trim_and_crop' in str(err)
    assert '1' in str(err)
    assert err.stage_name == 'trim_and_crop'
    assert err.stage_order == 1
    assert err.cause is cause
