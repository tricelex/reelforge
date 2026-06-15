"""Tests for the rendering.ffmpeg service module."""


def test_rendering_app_importable() -> None:
    import server.apps.rendering.ffmpeg  # noqa: F401, PLC0415

    assert True
