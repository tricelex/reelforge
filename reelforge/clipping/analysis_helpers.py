from __future__ import annotations

import logging
from datetime import UTC
from datetime import datetime
from typing import Any

logger = logging.getLogger("reelforge.clipping.analysis")


def run_speaker_diarization(video_path: str) -> dict[str, Any]:
    """Run PyAnnote speaker diarization. Returns dict with 'segments' list."""
    from reelforge.services.media.speaker_detection import SpeakerDetectionService

    service = SpeakerDetectionService()
    segments = service.diarize(video_path)
    return {
        "segments": [
            {"speaker_id": s.speaker_id, "start": s.start, "end": s.end}
            for s in segments
        ]
    }


def run_scene_detection(video_path: str) -> list[float]:
    """Run PySceneDetect content-aware scene detection.

    Returns a list of scene-cut timestamps in seconds.
    Falls back to empty list if detection fails.
    """
    try:
        from scenedetect import ContentDetector
        from scenedetect import detect

        scenes = detect(video_path, ContentDetector())
        return [scene[0].get_seconds() for scene in scenes]
    except Exception as exc:
        logger.warning(
            "Scene detection failed — continuing without scene cuts",
            extra={"video_path": video_path, "error": str(exc)},
        )
        return []


def run_face_detection_for_speakers(
    video_path: str,
    diarization: dict[str, Any],
) -> dict[str, list[dict]]:
    """Sample faces at key moments per speaker segment.

    Returns {speaker_id: [{"timestamp": float, "bbox": {...}}]} mapping.
    """
    from reelforge.services.media.speaker_detection import SpeakerDetectionService

    service = SpeakerDetectionService()
    speaker_faces: dict[str, list[dict]] = {}

    for segment in diarization.get("segments", []):
        speaker_id = segment["speaker_id"]
        start = segment["start"]
        end = segment["end"]
        # Sample up to 3 seconds of each segment
        sample_end = min(end, start + 3.0)
        face_data = service.detect_faces_for_segment(video_path, start, sample_end)
        if speaker_id not in speaker_faces:
            speaker_faces[speaker_id] = []
        for frame in face_data:
            if frame["faces"]:
                best = max(frame["faces"], key=lambda f: f["confidence"])
                speaker_faces[speaker_id].append(
                    {
                        "timestamp": frame["timestamp"],
                        "bbox": {
                            "x": best["x"],
                            "y": best["y"],
                            "w": best["w"],
                            "h": best["h"],
                        },
                    }
                )
    return speaker_faces


def _find_speaker_at_time(
    timestamp: float, segments: list[dict[str, Any]]
) -> str:
    """Return the speaker_id whose segment contains timestamp. Returns 'UNKNOWN' if none."""
    for seg in segments:
        if seg["start"] <= timestamp <= seg["end"]:
            return seg["speaker_id"]
    return "UNKNOWN"


def merge_transcript_with_diarization(
    transcript_json: dict[str, Any],
    diarization: dict[str, Any],
) -> list[dict[str, Any]]:
    """Assign speaker_id to each word based on time overlap with diarization segments."""
    words: list[dict[str, Any]] = []
    segments = diarization.get("segments", [])
    for segment in transcript_json.get("segments", []):
        for word_data in segment.get("words", []):
            speaker_id = _find_speaker_at_time(word_data["start"], segments)
            words.append(
                {
                    "word": word_data["word"].strip(),
                    "start": word_data["start"],
                    "end": word_data["end"],
                    "confidence": word_data.get("probability", 1.0),
                    "speaker_id": speaker_id,
                }
            )
    return words


def build_analysis_manifest(
    transcript: list[dict[str, Any]],
    diarization: dict[str, Any],
    face_mappings: dict[str, list[dict]],
    scene_cuts: list[float],
    candidates: list,
) -> dict[str, Any]:
    """Assemble the full analysis_manifest JSON (schema v2.0).

    Args:
        transcript: Word-level transcript with speaker_id from merge_transcript_with_diarization.
        diarization: Raw diarization dict with 'segments' list.
        face_mappings: Speaker → face sample list from run_face_detection_for_speakers.
        scene_cuts: Scene cut timestamps from run_scene_detection.
        candidates: List of ClipCandidate instances from ClipAnalysisService.analyze().
    """
    # Build speaker summaries
    speaker_map: dict[str, dict] = {}
    for seg in diarization.get("segments", []):
        sid = seg["speaker_id"]
        if sid not in speaker_map:
            speaker_map[sid] = {"id": sid, "label": None, "total_talk_time": 0.0, "segments": [], "face_samples": []}
        speaker_map[sid]["total_talk_time"] += seg["end"] - seg["start"]
        speaker_map[sid]["segments"].append({"start": seg["start"], "end": seg["end"]})

    for sid, face_samples in face_mappings.items():
        if sid in speaker_map:
            speaker_map[sid]["face_samples"] = face_samples

    ai_suggestions = []
    for candidate in candidates:
        ai_suggestions.append(
            {
                "start": candidate.start_sec,
                "end": candidate.end_sec,
                "score": candidate.relevance_score,
                "reason": candidate.reason,
                "hook_suggestion": candidate.hook_text,
                "title_suggestion": candidate.title,
                "dominant_speakers": [],
            }
        )

    return {
        "schema_version": "2.0",
        "transcript": transcript,
        "speakers": list(speaker_map.values()),
        "scene_cuts": scene_cuts,
        "ai_clip_suggestions": ai_suggestions,
        "waveform_url": None,
        "thumbnail_strip_url": None,
        "completed_at": datetime.now(UTC).isoformat(),
    }
