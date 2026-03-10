from __future__ import annotations

# ── Style presets → Flux Pro suffix strings ───────────────────────────────────

STYLE_MAP: dict[str, str] = {
    "cinematic_realism": (
        "cinematic photograph, 8K, shallow depth of field, professional colour grading, film grain"
    ),
    "flat_illustration": (
        "flat design illustration, bold geometric shapes, vibrant solid colours, "
        "minimal shadows, clean vector style"
    ),
    "dark_tech": (
        "dark futuristic tech aesthetic, neon accent lights, bokeh background, "
        "high contrast, cyberpunk mood"
    ),
    "corporate_clean": (
        "professional corporate photography, soft studio lighting, neutral background, "
        "business attire, high resolution"
    ),
}

_DEFAULT_STYLE = STYLE_MAP["cinematic_realism"]


def build_image_prompt(broll: dict) -> str:
    """Build a Flux Pro prompt from an enriched broll suggestion dict.

    Accepts either an ``AgentBRollSuggestion``-style dict or the stored
    ``BRollSuggestion`` format — both share the same field names.

    Args:
        broll: Dict with keys: subject, setting, lighting, camera_angle,
               colour_palette, style_preset, mood, description.

    Returns:
        A single comma-joined prompt string optimised for Flux Pro.
    """
    style_key = broll.get("style_preset", "cinematic_realism")
    style_suffix = STYLE_MAP.get(style_key, _DEFAULT_STYLE)

    palette_str = ""
    palette = broll.get("colour_palette", [])
    if palette:
        palette_str = "colour palette: " + ", ".join(str(c) for c in palette)

    parts = [
        broll.get("subject", "") or broll.get("description", ""),
        broll.get("setting", ""),
        f"{broll.get('mood', '')} mood" if broll.get("mood") else "",
        broll.get("lighting", ""),
        f"{broll.get('camera_angle', 'eye-level')} shot",
        broll.get("description", ""),
        palette_str,
        style_suffix,
        "no text, no watermarks, no UI elements, 16:9 aspect ratio, ultra detailed",
    ]
    return ", ".join(p for p in parts if p)
