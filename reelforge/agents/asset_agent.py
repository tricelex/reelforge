from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from agents import Agent
from agents import Tool

if TYPE_CHECKING:
    from reelforge.channels.models import Channel
    from reelforge.scripts.models import ScriptJob

logger = logging.getLogger("reelforge.agents.asset")


def build_asset_agent(channel: Channel, script_job: ScriptJob) -> Agent:
    """Build the asset generation agent.

    Helper functions defined within this factory to capture channel and script_job context.
    """

    def save_audio_segment(segment_id: int, audio_bytes: bytes) -> str:
        """Save voiceover segment to storage.

        TODO: Implement actual file storage logic.
        """
        logger.warning(
            "save_audio_segment called (placeholder) - segment_id=%s, size=%d bytes",
            segment_id,
            len(audio_bytes),
        )
        # Placeholder: return mock path using tempfile
        temp_dir = Path(tempfile.gettempdir()) / "reelforge" / "audio"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return str(temp_dir / f"mock_audio_segment_{segment_id}.mp3")

    def save_image(image_bytes: bytes, position_idx: int) -> str:
        """Save generated image to storage.

        TODO: Implement actual file storage logic.
        """
        logger.warning(
            "save_image called (placeholder) - position_idx=%d, size=%d bytes",
            position_idx,
            len(image_bytes),
        )
        # Placeholder: return mock path using tempfile
        temp_dir = Path(tempfile.gettempdir()) / "reelforge" / "images"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return str(temp_dir / f"mock_image_{position_idx}.jpg")

    def save_thumbnail(image_bytes: bytes, option_number: int) -> str:
        """Save thumbnail option to storage.

        TODO: Implement actual file storage logic.
        """
        logger.warning(
            "save_thumbnail called (placeholder) - option_number=%d, size=%d bytes",
            option_number,
            len(image_bytes),
        )
        # Placeholder: return mock path using tempfile
        temp_dir = Path(tempfile.gettempdir()) / "reelforge" / "thumbnails"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return str(temp_dir / f"mock_thumbnail_{option_number}.jpg")

    def _build_thumbnail_prompts(title: str, niche: str, brand_color: str) -> list[str]:
        """Generate thumbnail prompt variations.

        TODO: Implement more sophisticated prompt generation based on niche best practices.
        """
        logger.warning("_build_thumbnail_prompts called (placeholder) - title=%s, niche=%s", title, niche)
        return [
            f"YouTube thumbnail for '{title}' in {niche} niche, bold text overlay, {brand_color} accent",
            f"Eye-catching {niche} thumbnail: '{title}', dramatic lighting, professional design",
            f"High-impact thumbnail for {niche} video: '{title}', minimal text, vibrant colors",
        ]

    @Tool(name="generate_voiceover_segment", description="Generate TTS audio for a script segment.")
    def generate_voiceover_segment(segment_id: str, text: str, voice_settings: dict[str, Any]) -> dict[str, Any]:
        from reelforge.services.providers.registry import get_tts_provider

        tts = get_tts_provider(channel)
        response = tts.synthesize(
            text=text,
            voice_id=channel.tts_voice_id,
            stability=voice_settings.get("stability", channel.tts_stability),
            similarity_boost=voice_settings.get("similarity", channel.tts_similarity),
        )
        # Save file, return path
        path = save_audio_segment(segment_id, response.audio_bytes)
        return {"segment_id": segment_id, "path": path, "duration_sec": response.duration_sec}

    @Tool(name="generate_background_image", description="Generate a background image for a script section.")
    def generate_background_image(prompt: str, section: str, position_idx: int) -> dict[str, Any]:
        from reelforge.services.providers.registry import get_image_provider

        img_provider = get_image_provider(channel)
        responses = img_provider.generate(
            prompt=f"{prompt}. Photorealistic, cinematic, 16:9, no text, no faces.",
            width=1920,
            height=1080,
            num_images=2,
        )
        path = save_image(responses[0].image_bytes, position_idx)
        return {"path": path, "position_idx": position_idx, "prompt_used": prompt}

    @Tool(name="generate_thumbnail_options", description="Generate 3 thumbnail options for the video.")
    def generate_thumbnail_options(title: str, niche: str, brand_color: str) -> list[dict[str, Any]]:
        from reelforge.services.providers.registry import get_image_provider

        img_provider = get_image_provider(channel)
        options = []
        prompts = _build_thumbnail_prompts(title, niche, brand_color)
        for i, prompt in enumerate(prompts[:3]):
            response = img_provider.generate(prompt=prompt, width=1280, height=720, num_images=1)
            path = save_thumbnail(response[0].image_bytes, option_number=i)
            options.append({"option": i, "path": path, "prompt": prompt})
        return options

    @Tool(name="select_background_music", description="Select the best music track for the video's tone.")
    def select_background_music(niche: str, script_tone: str) -> dict[str, str]:
        import os
        import random

        tone_map = {
            "inspiring": "inspiring_cinematic",
            "educational": "calm_ambient",
            "dramatic": "dramatic_corporate",
            "motivational": "upbeat_motivational",
        }
        style = tone_map.get(script_tone.lower(), "subtle_lofi")
        music_dir = f"storage/music/{style}/"
        files = [f for f in os.listdir(music_dir) if f.endswith(".mp3")]
        chosen = random.choice(files)
        return {"style": style, "path": music_dir + chosen}

    return Agent(
        name="AssetAgent",
        model="gpt-4o",
        instructions=f"""
        You are responsible for generating all media assets for a YouTube video.
        Channel: {channel.name}, Niche: {channel.target_niches}
        Voice: {channel.tts_voice_name}

        PROCESS:
        1. For each script segment: generate_voiceover_segment
        2. For each B-roll note in script: generate_background_image
        3. generate_thumbnail_options (3 options)
        4. select_background_music based on script tone
        5. Return asset manifest with all file paths and timing data

        PARALLEL EXECUTION: Process voiceover segments in batches of 5.
        RETRY: If any generation fails, retry once with simplified prompt.
        """,
        tools=[
            generate_voiceover_segment,
            generate_background_image,
            generate_thumbnail_options,
            select_background_music,
        ],
    )
