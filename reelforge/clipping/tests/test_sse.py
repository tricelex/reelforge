from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


def test_emit_job_event_publishes_to_redis():
    with patch("reelforge.clipping.sse._redis_client") as mock_redis:
        from reelforge.clipping.sse import emit_job_event

        emit_job_event("job-123", "status_changed", {"status": "DOWNLOADING"})

        mock_redis.publish.assert_called_once()
        channel, payload = mock_redis.publish.call_args[0]
        assert channel == "clipping:job:job-123"
        data = json.loads(payload)
        assert data["type"] == "status_changed"
        assert data["job_id"] == "job-123"
        assert data["status"] == "DOWNLOADING"


def test_job_event_stream_yields_sse_format():
    mock_pubsub = MagicMock()
    mock_pubsub.listen.return_value = [
        {"type": "subscribe", "data": 1},
        {"type": "message", "data": b'{"type":"status_changed","job_id":"j1"}'},
    ]
    with patch("reelforge.clipping.sse._redis_client") as mock_redis:
        mock_redis.pubsub.return_value = mock_pubsub
        from reelforge.clipping.sse import job_event_stream

        events = list(job_event_stream("j1"))

    assert events[0] == "event: connected\ndata: {}\n\n"
    assert events[1].startswith("data: ")
    assert '"type":"status_changed"' in events[1]
