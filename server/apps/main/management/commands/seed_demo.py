"""Seed demo data for all pipeline kinds, story formats, prompt templates, and a demo channel.

Run with:  python manage.py seed_demo
Idempotent — safe to re-run; uses update_or_create throughout.
"""

from typing import Any, override

from django.core.management.base import BaseCommand

# ---------------------------------------------------------------------------
# Story Format constants
# ---------------------------------------------------------------------------

_STORY_FORMATS: list[dict[str, Any]] = [
    {
        'key': 'factual_documentary',
        'name': 'Factual Documentary',
        'fiction': False,
        'narration_pov': 'narrator',
        'beats': [
            {
                'name': 'hook',
                'description': (
                    'Open on the single most dramatic or surprising moment. '
                    'Drop the viewer into the action before any context.'
                ),
            },
            {
                'name': 'context',
                'description': (
                    'Establish the historical or factual backdrop. '
                    'Answer: when, where, who, and why it matters.'
                ),
            },
            {
                'name': 'evidence',
                'description': (
                    'Present key facts, events, and expert perspectives in '
                    'chronological or logical order. Build the case.'
                ),
            },
            {
                'name': 'implications',
                'description': (
                    'Zoom out: what did this change, what does it reveal, '
                    'why should a modern viewer care?'
                ),
            },
            {
                'name': 'call_to_action',
                'description': (
                    'End with a memorable insight or open question that '
                    'invites reflection and re-engagement.'
                ),
            },
        ],
        'pacing': {
            'hook': 45,
            'context': 90,
            'evidence': 480,
            'implications': 120,
            'call_to_action': 45,
        },
        'music_mood_map': {
            'hook': 'tense',
            'context': 'atmospheric',
            'evidence': 'dramatic',
            'implications': 'reflective',
            'call_to_action': 'uplifting',
        },
        'prompt_overrides': {},
    },
    {
        'key': 'true_crime_case',
        'name': 'True Crime Case',
        'fiction': False,
        'narration_pov': 'investigative_narrator',
        'beats': [
            {
                'name': 'cold_open',
                'description': (
                    'Start at the moment of discovery or arrest. '
                    'Tease the mystery without revealing the answer.'
                ),
            },
            {
                'name': 'victim_background',
                'description': (
                    'Humanise the victim and establish the ordinary world '
                    'before the crime disrupted it.'
                ),
            },
            {
                'name': 'crime',
                'description': (
                    'Reconstruct what happened with available evidence. '
                    'Be precise about what is known vs. speculated.'
                ),
            },
            {
                'name': 'investigation',
                'description': (
                    'Follow the investigators — the leads, the dead ends, '
                    'the turning points, and the key evidence.'
                ),
            },
            {
                'name': 'resolution',
                'description': (
                    'Present the outcome and its aftermath. '
                    'Reflect on what justice meant (or failed to mean) in this case.'
                ),
            },
        ],
        'pacing': {
            'cold_open': 60,
            'victim_background': 90,
            'crime': 150,
            'investigation': 300,
            'resolution': 120,
        },
        'music_mood_map': {
            'cold_open': 'ominous',
            'victim_background': 'melancholic',
            'crime': 'tense',
            'investigation': 'suspenseful',
            'resolution': 'sombre',
        },
        'prompt_overrides': {},
    },
    {
        'key': 'educational_explainer',
        'name': 'Educational Explainer',
        'fiction': False,
        'narration_pov': 'teacher',
        'beats': [
            {
                'name': 'question',
                'description': (
                    'Open with a curiosity-provoking question or counterintuitive claim '
                    'that the video will answer.'
                ),
            },
            {
                'name': 'why_it_matters',
                'description': (
                    'Establish stakes: why should the viewer care about knowing this? '
                    'Connect to everyday life or widely-held assumptions.'
                ),
            },
            {
                'name': 'explanation',
                'description': (
                    'Explain the core concept step by step using analogies, '
                    'visual comparisons, and concrete examples.'
                ),
            },
            {
                'name': 'examples',
                'description': (
                    'Demonstrate the concept in two or three real-world cases '
                    'that reinforce and extend the core explanation.'
                ),
            },
            {
                'name': 'summary',
                'description': (
                    'Summarise the key takeaway in one clear sentence. '
                    'Answer the opening question directly.'
                ),
            },
        ],
        'pacing': {
            'question': 30,
            'why_it_matters': 60,
            'explanation': 300,
            'examples': 180,
            'summary': 30,
        },
        'music_mood_map': {
            'question': 'curious',
            'why_it_matters': 'engaging',
            'explanation': 'focused',
            'examples': 'illustrative',
            'summary': 'resolved',
        },
        'prompt_overrides': {},
    },
    {
        'key': 'motivational_story',
        'name': 'Motivational Story',
        'fiction': False,
        'narration_pov': 'coach',
        'beats': [
            {
                'name': 'status_quo',
                'description': (
                    'Paint the ordinary world — the struggle, the limitation, '
                    'the widespread belief that things cannot change.'
                ),
            },
            {
                'name': 'inciting_event',
                'description': (
                    'The moment everything shifts: a decision, a disaster, an encounter '
                    'that forces a new path forward.'
                ),
            },
            {
                'name': 'struggle',
                'description': (
                    'Follow the protagonist through setbacks, doubt, and obstacles '
                    'that test their resolve.'
                ),
            },
            {
                'name': 'breakthrough',
                'description': (
                    'The turning point where persistence, insight, or help '
                    'transforms the situation. Show the work.'
                ),
            },
            {
                'name': 'lesson',
                'description': (
                    'Distil the transferable principle. Address the viewer directly: '
                    'what can they do with this insight today?'
                ),
            },
        ],
        'pacing': {
            'status_quo': 60,
            'inciting_event': 60,
            'struggle': 240,
            'breakthrough': 120,
            'lesson': 60,
        },
        'music_mood_map': {
            'status_quo': 'subdued',
            'inciting_event': 'tense',
            'struggle': 'determined',
            'breakthrough': 'triumphant',
            'lesson': 'uplifting',
        },
        'prompt_overrides': {},
    },
    {
        'key': 'fantasy_lore',
        'name': 'Fantasy Lore',
        'fiction': True,
        'narration_pov': 'narrator',
        'beats': [
            {
                'name': 'world_setup',
                'description': (
                    'Establish the world: its rules, its factions, the tension '
                    'that defines daily life in this place.'
                ),
            },
            {
                'name': 'characters',
                'description': (
                    'Introduce the key figures — their goals, flaws, '
                    'and the relationships that will drive the conflict.'
                ),
            },
            {
                'name': 'conflict',
                'description': (
                    'The event that disrupts the equilibrium. Forces collide. '
                    'Stakes become clear.'
                ),
            },
            {
                'name': 'climax',
                'description': (
                    'The decisive confrontation or revelation that resolves '
                    'the central conflict — for better or worse.'
                ),
            },
            {
                'name': 'denouement',
                'description': (
                    'The aftermath: how the world and characters are changed. '
                    'Hint at what comes next.'
                ),
            },
        ],
        'pacing': {
            'world_setup': 90,
            'characters': 90,
            'conflict': 180,
            'climax': 180,
            'denouement': 60,
        },
        'music_mood_map': {
            'world_setup': 'mystical',
            'characters': 'adventurous',
            'conflict': 'ominous',
            'climax': 'epic',
            'denouement': 'bittersweet',
        },
        'prompt_overrides': {},
    },
]


# ---------------------------------------------------------------------------
# Prompt Template + Version constants
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATES: list[dict[str, Any]] = [
    {
        'key': 'research',
        'name': 'Research Brief',
        'scope': 'GLOBAL',
        'description': (
            'Generates a comprehensive research brief for the video topic. '
            'Used by the research stage before outline creation.'
        ),
        'system_prompt': (
            'You are a senior research analyst for a YouTube documentary channel. '
            'Your job is to produce comprehensive, accurate research briefs that '
            'scriptwriters use to craft compelling educational videos. Prioritise '
            'verifiable facts from primary and secondary sources. Note conflicting '
            'scholarly interpretations. Identify the most emotionally resonant angle '
            'for a general adult audience. Return structured JSON.'
        ),
        'user_prompt': (
            'Research the following topic for our YouTube channel.\n\n'
            'Topic: {{ topic }}\n\n'
            '{% if niche.audience %}Target Audience: {{ niche.audience }}\n{% endif %}'
            '{% if niche.angle %}Editorial Angle: {{ niche.angle }}\n{% endif %}'
            '{% if niche.banned_topics %}Avoid these subjects: '
            "{{ niche.banned_topics | join(', ') }}\n{% endif %}"
            '\nProduce a research brief with:\n'
            '1. A concise summary (2–3 sentences)\n'
            '2. Core verified facts and timeline\n'
            '3. Key figures and their motivations\n'
            '4. Three compelling narrative angles\n'
            '5. Five emotional hooks suitable for an opening\n'
            '6. Primary and secondary sources with relevance scores\n'
            '7. Lesser-known details most viewers will not know\n\n'
            'Corroboration requirement: for every entry in key_facts, at '
            'least 2 of your listed sources must independently state that '
            'same fact — put the matching wording in each corroborating '
            "source's own key_facts list, not just the brief's key_facts. "
            'Prefer primary/archival/academic sources when available. A '
            'fact with only one supporting source should either be dropped '
            'or you should find a second source before including it.'
        ),
    },
    {
        'key': 'outline',
        'name': 'Video Outline',
        'scope': 'GLOBAL',
        'description': (
            'Creates a chapter-based video outline from the research brief. '
            'Incorporates StoryFormat beats and retention devices.'
        ),
        'system_prompt': (
            'You are an expert YouTube video outline specialist. '
            'You create chapter-based structures that maximise viewer retention '
            'using proven storytelling frameworks. Each chapter builds tension, '
            'reveals information progressively, and includes retention devices '
            'such as cliffhangers, callbacks, and unanswered questions. '
            'Return structured JSON.'
        ),
        'user_prompt': (
            'Create a detailed video outline for:\n\n'
            'Topic: {{ topic }}\n\n'
            'Research Brief:\n{{ upstream.research.brief | tojson(indent=2) }}\n\n'
            '{% if format %}'
            'Story Format: {{ format.name }}\n'
            'Narrative Beats: {{ format.beats | tojson }}\n'
            'Narration POV: {{ format.narration_pov }}\n'
            '{% endif %}'
            '{% if niche.audience %}Target Audience: {{ niche.audience }}\n{% endif %}'
            '\nCreate 6–10 chapters. For each chapter provide:\n'
            '- index (0-based)\n'
            '- title (compelling chapter name)\n'
            '- hook (the opening question or claim for this chapter)\n'
            '- key_beats (list of 3–5 information beats to cover)\n'
            '- retention_device (cliffhanger / callback / teaser / question)\n'
            '- target_seconds (estimated chapter duration in seconds)'
        ),
    },
    {
        'key': 'script',
        'name': 'Narration Script',
        'scope': 'GLOBAL',
        'description': (
            'Writes the full narration script chapter by chapter. '
            'Uses channel lore document for voice consistency.'
        ),
        'system_prompt': (
            'You are a professional YouTube scriptwriter specialising in educational '
            'documentary content. You write in a natural, conversational voice that '
            'sounds authentic when read aloud. Vary sentence length. Use vivid, '
            'concrete language and avoid academic jargon unless immediately explained. '
            'Every chapter must end with a closing line that drives viewers to continue '
            'watching. Every chapter also needs commentary: 1-3 sentences of genuine '
            'analysis or a stated opinion, distinct from the narration, reflecting a '
            'real editorial point of view on the material — not a restatement of what '
            'was just narrated. Return structured JSON.'
        ),
        'user_prompt': (
            'Write a complete narration script for:\n\n'
            'Topic: {{ topic }}\n\n'
            'Chapter Outline:\n{{ upstream.outline.chapters | tojson(indent=2) }}\n\n'
            'Research Brief (for accuracy):\n'
            '{{ upstream.research.brief | tojson(indent=2) }}\n\n'
            '{% if niche.angle %}Editorial Angle: {{ niche.angle }}\n{% endif %}'
            '{% if format %}Narration POV: {{ format.narration_pov }}\n{% endif %}'
            '{% if lore %}Channel Style Guide:\n{{ lore }}\n{% endif %}'
            '\nFor each chapter write:\n'
            '- index (matching outline)\n'
            '- title\n'
            '- narration (complete spoken text — natural, conversational)\n'
            '- closing_line (the last sentence that hooks the viewer into the next chapter)\n'
            '- commentary (1-3 sentences of genuine analysis or a stated '
            'opinion — not a restatement of the narration)'
        ),
    },
    {
        'key': 'scene_breakdown',
        'name': 'Scene Breakdown',
        'scope': 'GLOBAL',
        'description': (
            'Splits the narration script into individual visual scenes of 6–12 seconds each.'
        ),
        'system_prompt': (
            'You are a visual producer for a YouTube documentary channel. '
            'You translate narration scripts into precise scene-by-scene visual briefs. '
            'Each scene describes exactly what appears on screen while the narrator speaks. '
            'HARD CONSTRAINTS: narration_text must be 10–35 words. '
            'foreground_cast must contain at most 2 names. '
            'Each scene should last 6–12 seconds. '
            'Return structured JSON.'
        ),
        'user_prompt': (
            'Break the following script into visual scenes:\n\n'
            'Topic: {{ topic }}\n\n'
            'Full Script:\n{{ upstream.script.chapters | tojson(indent=2) }}\n\n'
            '{% if character %}Main Character: {{ character.name }}\n{% endif %}'
            '\nFor each scene provide:\n'
            '- scene_index (0-based, sequential across all chapters)\n'
            '- chapter_index\n'
            '- narration_text (exactly 10–35 words of spoken narration)\n'
            '- visual_description (what the viewer sees — specific and filmic)\n'
            '- foreground_cast (list of character names on screen, max 2)\n'
            '- setting (location or environment)\n'
            '- mood (single word: tense / dramatic / contemplative / joyful etc.)\n'
            '- duration_hint_s (estimated seconds, 6–12)'
        ),
    },
    {
        'key': 'visual_prompts',
        'name': 'Visual Prompts',
        'scope': 'GLOBAL',
        'description': (
            'Generates Flux-compatible image prompts for each scene in the breakdown.'
        ),
        'system_prompt': (
            'You are an AI image prompt engineer specialising in Flux diffusion models. '
            'You write highly specific, technically detailed prompts that produce '
            'photorealistic or stylised images for documentary video content. '
            'Use lighting descriptors, composition terms, colour grading language, '
            'and camera/lens specifications. Each prompt should be 80–200 words. '
            'Flag any scenes with sensitive content in safety_flagged. '
            'Return structured JSON.'
        ),
        'user_prompt': (
            'Generate Flux-compatible image prompts for each scene:\n\n'
            'Topic: {{ topic }}\n\n'
            'Scenes:\n{{ upstream.scene_breakdown.scenes | tojson(indent=2) }}\n\n'
            '{% if character %}'
            'Main Character Appearance:\n'
            'Name: {{ character.name }}\n'
            'Description: {{ character.appearance_prompt }}\n'
            '{% endif %}'
            '\nFor each scene produce:\n'
            '- scene_index (matching input)\n'
            '- prompt (detailed Flux image prompt, 80–200 words)\n'
            '- negative_prompt (elements to exclude)\n'
            '- style_tags (list of 3–5 style keywords)\n'
            '- safety_flagged (true if content may violate image generation policies)'
        ),
    },
    {
        'key': 'music_plan',
        'name': 'Music Plan',
        'scope': 'GLOBAL',
        'description': (
            'Selects background music tracks from the channel library for each chapter. '
            'Aligns mood choices with the StoryFormat music_mood_map.'
        ),
        'system_prompt': (
            'You are a music supervisor for YouTube documentary content. '
            'You select background music tracks that enhance emotional impact at each '
            'chapter. You understand pacing, mood transitions, and how music affects '
            'viewer retention. Choose from the provided library asset IDs only. '
            'Return structured JSON.'
        ),
        'user_prompt': (
            'Create a music plan for the following video:\n\n'
            'Topic: {{ topic }}\n\n'
            'Chapter/Scene Breakdown:\n'
            '{{ upstream.scene_breakdown.scenes | tojson(indent=2) }}\n\n'
            '{% if format %}'
            'Music Mood Map: {{ format.music_mood_map | tojson }}\n'
            '{% endif %}'
            'Available Library Asset IDs by tag:\n'
            '{{ library_tracks | default([]) | tojson }}\n\n'
            'For each chapter provide:\n'
            '- chapter_idx\n'
            '- library_asset_id (must be from the available list above)\n'
            '- gain_db (volume adjustment: -20 to 0, suggest -18 for bed music)\n'
            '- mood (selected mood tag matching music_mood_map)\n'
            '- rationale (one sentence explaining why this track fits)'
        ),
    },
    {
        'key': 'metadata',
        'name': 'YouTube Metadata',
        'scope': 'GLOBAL',
        'description': (
            'Generates SEO-optimised YouTube title, description, tags, and category.'
        ),
        'system_prompt': (
            'You are a YouTube SEO specialist with expertise in optimising video titles, '
            'descriptions, and tags for maximum organic discovery. Write titles that are '
            'compelling AND search-friendly. Descriptions use natural keyword density. '
            'Tags are specific and relevant. '
            'CONSTRAINT: title must be 60 characters or fewer. '
            'Return structured JSON.'
        ),
        'user_prompt': (
            'Create YouTube metadata for:\n\n'
            'Topic: {{ topic }}\n\n'
            'Script Chapters (for keyword context):\n'
            '{{ upstream.script.chapters | tojson(indent=2) }}\n\n'
            'Alignment Timestamps (for chapter markers):\n'
            '{{ upstream.alignment.scenes | tojson(indent=2) }}\n\n'
            '{% if niche.audience %}Target Audience: {{ niche.audience }}\n{% endif %}'
            '\nProduce:\n'
            '- title (compelling, SEO-optimised, maximum 60 characters)\n'
            '- description (150–300 word description with keywords and chapter timestamps)\n'
            '- tags (list of 15–20 specific, relevant tags)\n'
            '- category (YouTube category name, e.g. "Education", "Entertainment")'
        ),
    },
    {
        'key': 'thumbnail',
        'name': 'Thumbnail Concepts',
        'scope': 'GLOBAL',
        'description': (
            'Generates high-CTR thumbnail concept descriptions for the video.'
        ),
        'system_prompt': (
            'You are a YouTube thumbnail designer. You create concepts for high-CTR '
            'thumbnails that are visually striking, emotionally evocative, and readable '
            'at small sizes. You understand contrast, focal points, text overlay rules, '
            'and the role of facial expressions in click-through behaviour. '
            'Return structured JSON.'
        ),
        'user_prompt': (
            'Design thumbnail concepts for:\n\n'
            'Topic: {{ topic }}\n\n'
            'Opening Chapter (for context):\n'
            '{{ upstream.script.chapters[0] | tojson }}\n\n'
            '{% if character %}'
            'On-Screen Character: {{ character.name }}\n'
            'Appearance: {{ character.appearance_prompt[:300] }}\n'
            '{% endif %}'
            '{% if channel.branding %}'
            'Brand Palette: {{ channel.branding.thumbnail_palette | tojson }}\n'
            '{% endif %}'
            '\nCreate {{ config.candidates | default(3) }} thumbnail concepts.\n'
            'For each concept provide:\n'
            '- concept (full visual description of the thumbnail layout)\n'
            '- headline_text (bold overlay text, maximum 4 words)\n'
            '- emotion (facial expression or mood: shocked / curious / intense etc.)\n'
            '- composition (layout: face-left-text-right / full-face / split etc.)\n'
            '- ctr_rationale (one sentence: why this will earn clicks)'
        ),
    },
    {
        'key': 'clip_analyze',
        'name': 'Clip Analysis',
        'scope': 'GLOBAL',
        'description': (
            'Identifies viral clip candidates from a long-form transcript. '
            'Used by the clip_analyze stage in CLIPPING pipelines.'
        ),
        'system_prompt': (
            'You are a social media clip curator for a YouTube channel. '
            'You identify high-impact moments in long-form transcripts that will '
            'perform well as short-form clips on YouTube Shorts, TikTok, and Instagram Reels. '
            'Prioritise: surprising revelations, emotional peaks, quotable insights, '
            'and moments that are self-contained stories. '
            'Each clip should be 30–90 seconds. '
            'Return structured JSON.'
        ),
        'user_prompt': (
            'Analyse the following transcript and identify the best clip candidates:\n\n'
            'Source Video Duration: {{ upstream.clip_transcribe.duration_sec }}s\n\n'
            'Transcript:\n{{ transcript_text }}\n\n'
            'Clips Requested: {{ config.clips_requested | default(5) }}\n\n'
            'For each clip candidate provide:\n'
            '- start_sec (float — clip start time)\n'
            '- end_sec (float — clip end time, 30–90 seconds after start)\n'
            '- title (punchy, shareable clip title)\n'
            '- hook_text (opening text overlay that stops the scroll, max 8 words)\n'
            '- caption_template (social media caption template with placeholder [CHANNEL])\n'
            '- relevance_score (0.0–1.0 — predicted virality/engagement score)\n'
            '- reason (one sentence: why this moment will perform well as a clip)'
        ),
    },
]


# ---------------------------------------------------------------------------
# Blueprint graph constants
# ---------------------------------------------------------------------------

_LONGFORM_V1_GRAPH: dict[str, object] = {
    'stages': [
        {'key': 'research', 'depends_on': [], 'queue': 'api'},
        {'key': 'outline', 'depends_on': ['research'], 'queue': 'api'},
        {'key': 'script', 'depends_on': ['outline'], 'queue': 'api'},
        {'key': 'scene_breakdown', 'depends_on': ['script'], 'queue': 'api'},
        {
            'key': 'narrative_qc',
            'depends_on': ['scene_breakdown'],
            'queue': 'api',
        },
        {
            'key': 'visual_prompts',
            'depends_on': ['narrative_qc'],
            'queue': 'api',
        },
        {
            'key': 'image_gen',
            'depends_on': ['visual_prompts'],
            'queue': 'api',
            'fan_out': 'scenes',
            'config': {
                'model': 'fal-ai/flux-kontext-pro',
                'use_character_ref': True,
            },
        },
        {
            'key': 'tts',
            'depends_on': ['narrative_qc'],
            'queue': 'api',
            'fan_out': 'chapters',
            'config': {'provider': 'elevenlabs'},
        },
        {
            'key': 'motion',
            'depends_on': ['image_gen'],
            'queue': 'render',
            'fan_out': 'scenes',
            'config': {
                'hero_ratio': 0.15,
                'i2v_model': 'fal-ai/kling-video/v2.1/standard/image-to-video',
            },
        },
        {'key': 'alignment', 'depends_on': ['tts'], 'queue': 'gpu'},
        {
            'key': 'music_plan',
            'depends_on': ['scene_breakdown'],
            'queue': 'api',
        },
        {
            'key': 'thumbnail',
            'depends_on': ['script'],
            'queue': 'api',
            'config': {'candidates': 3},
        },
        {
            'key': 'metadata',
            'depends_on': ['script', 'alignment'],
            'queue': 'api',
        },
        {
            'key': 'assembly',
            'depends_on': ['motion', 'tts', 'alignment', 'music_plan'],
            'queue': 'render',
        },
        {
            'key': 'qc',
            'depends_on': ['assembly'],
            'queue': 'render',
        },
    ],
}

# Shorts: no motion (GPU cost), no music_plan, no thumbnail.
# Assembly runs on static images + VO in 9:16 vertical format.
_SHORTS_V1_GRAPH: dict[str, object] = {
    'stages': [
        {'key': 'research', 'depends_on': [], 'queue': 'api'},
        {'key': 'outline', 'depends_on': ['research'], 'queue': 'api'},
        {'key': 'script', 'depends_on': ['outline'], 'queue': 'api'},
        {'key': 'scene_breakdown', 'depends_on': ['script'], 'queue': 'api'},
        {
            'key': 'narrative_qc',
            'depends_on': ['scene_breakdown'],
            'queue': 'api',
        },
        {
            'key': 'visual_prompts',
            'depends_on': ['narrative_qc'],
            'queue': 'api',
        },
        {
            'key': 'image_gen',
            'depends_on': ['visual_prompts'],
            'queue': 'api',
            'fan_out': 'scenes',
            'config': {
                'model': 'fal-ai/flux-kontext-pro',
                'use_character_ref': True,
            },
        },
        {
            'key': 'tts',
            'depends_on': ['narrative_qc'],
            'queue': 'api',
            'fan_out': 'chapters',
            'config': {'provider': 'elevenlabs'},
        },
        {'key': 'alignment', 'depends_on': ['tts'], 'queue': 'gpu'},
        {
            'key': 'metadata',
            'depends_on': ['script', 'alignment'],
            'queue': 'api',
            'config': {'format': 'shorts'},
        },
        {
            'key': 'assembly',
            'depends_on': ['image_gen', 'tts', 'alignment'],
            'queue': 'render',
            'config': {
                'format': 'shorts',
                'target_duration_s': 60,
                'aspect_ratio': '9:16',
            },
        },
        {'key': 'qc', 'depends_on': ['assembly'], 'queue': 'render'},
    ],
}

_CLIPPING_V1_GRAPH: dict[str, object] = {
    'stages': [
        {'key': 'clip_ingest', 'depends_on': []},
        {'key': 'clip_transcribe', 'depends_on': ['clip_ingest']},
        {
            'key': 'clip_analyze',
            'depends_on': ['clip_transcribe'],
            'config': {'clips_requested': 5},
        },
        {
            'key': 'clip_approval_gate',
            'depends_on': ['clip_analyze'],
            'gate': True,
        },
        {'key': 'clip_render', 'depends_on': ['clip_approval_gate']},
        {'key': 'clip_distribute', 'depends_on': ['clip_render']},
    ],
}

_CLIPPING_V1_MANUAL_GRAPH: dict[str, object] = {
    'stages': [
        {'key': 'clip_ingest', 'depends_on': []},
        {'key': 'clip_transcribe', 'depends_on': ['clip_ingest']},
        {'key': 'clip_manual_setup', 'depends_on': ['clip_transcribe']},
        {
            'key': 'clip_approval_gate',
            'depends_on': ['clip_manual_setup'],
            'gate': True,
        },
        {'key': 'clip_render', 'depends_on': ['clip_approval_gate']},
        {'key': 'clip_distribute', 'depends_on': ['clip_render']},
    ],
}

# ---------------------------------------------------------------------------
# Demo channel data
# ---------------------------------------------------------------------------

_DEMO_CHANNEL_LORE = """\
HISTORY EXPLAINED — CHANNEL STYLE GUIDE

VOICE & TONE
Our narrator is authoritative but never condescending. We speak directly to a
curious adult audience who already knows the basics — we are here to reveal what
is beneath the surface. Use active voice. Vary sentence length deliberately: short
sentences for impact, longer ones to build context. Avoid jargon unless immediately
explained in plain language.

FACTUAL STANDARDS
Every claim must be supported by historical consensus or clearly attributed to a
specific scholar or source. When historians disagree, acknowledge the debate honestly
and state where the weight of evidence falls. Never sensationalise or exaggerate for
dramatic effect — reality is dramatic enough.

STORYTELLING PRINCIPLES
1. Start in the middle of the action, not at the beginning of a chronology.
2. Humanise historical figures — they had fears, ambitions, blind spots, and bad days.
3. Draw modern parallels only when they genuinely illuminate the past, not for shock value.
4. End every chapter with a question or revelation that demands the viewer keep watching.
5. Treat the audience as intelligent adults who will fact-check us.

THINGS WE NEVER DO
- Reduce complex events to single causes or single villains.
- Apply anachronistic moral frameworks without acknowledging historical context.
- Exaggerate suffering or body counts for shock value.
- Present fringe academic theories as mainstream scholarship without flagging them.
- Use filler phrases: "In conclusion", "As we can see", "It goes without saying".

CHANNEL IDENTITY
We are the channel that makes you feel like you are sitting with a brilliant professor
who happens to be an expert storyteller. By the end of every video, the viewer should
think: "I had no idea history was this fascinating."
"""

_DEMO_CHARACTER_APPEARANCE = """\
Dr. Marcus Webb, a distinguished historian in his mid-fifties. Silver-streaked dark
hair, neatly groomed short beard. Wearing a charcoal tweed jacket with brown leather
elbow patches over a dark navy shirt, no tie. Warm, intelligent brown eyes with
slight crow's feet suggesting a lifetime of reading and thinking. Seated at a grand
mahogany desk in a dimly lit private library, floor-to-ceiling bookshelves visible
behind him, warm amber reading lamp casting directional light from left. Photorealistic,
cinematic colour grading, shallow depth of field, 50mm portrait lens, film grain.
Expression: engaged, curious, slightly conspiratorial — as though about to share a
secret the viewer will not hear anywhere else.
"""

_DEMO_CHARACTER_PERSONA = """\
Dr. Marcus Webb is a former Oxford history professor turned full-time documentary
narrator. He speaks with the measured authority of someone who has spent decades
separating myth from fact, but with the warmth of someone who genuinely loves sharing
what he has found. He addresses viewers by implication as fellow curious minds — never
talking down, always inviting them into the investigation alongside him. He uses precise
language but is not afraid of a well-placed colloquialism when it lands the point better.
His natural register is serious, but punctuated by dry wit and occasional genuine wonder
at the strangeness of historical events. He never editorialises beyond what the evidence
supports, and when he does offer an interpretation, he signals it clearly.
"""


class Command(BaseCommand):
    """Seed demo data for all pipeline kinds, story formats, prompts, and a demo channel."""

    help = 'Seed demo story formats, prompt templates, blueprints, and a fully-configured demo channel (idempotent)'

    @override
    def handle(self, *args: object, **options: object) -> None:
        """Run all seed steps in dependency order."""
        self._seed_story_formats()
        self._seed_prompt_templates()
        self._seed_blueprints()
        self._seed_demo_channel()

    # ------------------------------------------------------------------
    # Step 1 — Story formats
    # ------------------------------------------------------------------

    def _seed_story_formats(self) -> None:
        from server.apps.prompts.models import StoryFormat  # noqa: PLC0415

        for data in _STORY_FORMATS:
            key = data['key']
            sf, created = StoryFormat.objects.update_or_create(
                key=key,
                defaults={
                    'name': data['name'],
                    'fiction': data['fiction'],
                    'narration_pov': data['narration_pov'],
                    'beats': data['beats'],
                    'pacing': data['pacing'],
                    'music_mood_map': data['music_mood_map'],
                    'prompt_overrides': data['prompt_overrides'],
                    'is_active': True,
                },
            )
            action = 'Created' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'  {action} story format: {sf}'))

        self.stdout.write(
            self.style.SUCCESS(f'[1/4] Story formats: {len(_STORY_FORMATS)} seeded.'),
        )

    # ------------------------------------------------------------------
    # Step 2 — Prompt templates + active versions
    # ------------------------------------------------------------------

    def _seed_prompt_templates(self) -> None:
        from server.apps.generation.logic.constants import (  # noqa: PLC0415
            DEFAULT_LLM_MODEL,
        )
        from server.apps.prompts.models import (  # noqa: PLC0415
            PromptTemplate,
            PromptVersion,
        )

        for data in _PROMPT_TEMPLATES:
            key = data['key']
            template, created = PromptTemplate.objects.update_or_create(
                key=key,
                defaults={
                    'name': data['name'],
                    'scope': data['scope'],
                    'description': data['description'],
                },
            )
            action = 'Created' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'  {action} template: {template}'))

            PromptVersion.objects.update_or_create(
                template=template,
                version=1,
                defaults={
                    'system_prompt': data['system_prompt'],
                    'user_prompt': data['user_prompt'],
                    'model': DEFAULT_LLM_MODEL,
                    'temperature': 1.0,
                    'max_tokens': 8192,
                    'is_active': True,
                },
            )

        self.stdout.write(
            self.style.SUCCESS(
                f'[2/4] Prompt templates: {len(_PROMPT_TEMPLATES)} seeded '
                f'(each with an active v1).',
            ),
        )

    # ------------------------------------------------------------------
    # Step 3 — Pipeline blueprints
    # ------------------------------------------------------------------

    def _seed_blueprints(self) -> None:
        from server.apps.pipelines.models import (  # noqa: PLC0415
            PipelineBlueprint,
            PipelineKind,
        )

        blueprints = [
            ('longform_v1', PipelineKind.LONGFORM, _LONGFORM_V1_GRAPH),
            ('shorts_v1', PipelineKind.SHORTS, _SHORTS_V1_GRAPH),
            ('clipping_v1', PipelineKind.CLIPPING, _CLIPPING_V1_GRAPH),
            (
                'clipping_v1_manual',
                PipelineKind.CLIPPING,
                _CLIPPING_V1_MANUAL_GRAPH,
            ),
        ]

        for name, kind, graph in blueprints:
            bp, created = PipelineBlueprint.objects.update_or_create(
                name=name,
                kind=kind,
                defaults={'graph': graph, 'is_active': True},
            )
            action = 'Created' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'  {action} blueprint: {bp}'))

        self.stdout.write(
            self.style.SUCCESS(f'[3/4] Blueprints: {len(blueprints)} seeded.'),
        )

    # ------------------------------------------------------------------
    # Step 4 — Demo channel (fully configured)
    # ------------------------------------------------------------------

    def _seed_demo_channel(self) -> None:
        from server.apps.channels.models import (  # noqa: PLC0415
            Channel,
            ChannelBranding,
            ChannelKind,
            Character,
            CharacterDesignMode,
            CharacterOrigin,
            CharacterStatus,
            NicheConfig,
            PublishMode,
        )
        from server.apps.ideas.logic.constants import (  # noqa: PLC0415
            IdeaStatus,
        )
        from server.apps.ideas.models import TopicIdea  # noqa: PLC0415
        from server.apps.prompts.models import StoryFormat  # noqa: PLC0415

        # Channel
        channel, ch_created = Channel.objects.update_or_create(
            name='History Explained (Demo)',
            defaults={
                'kind': ChannelKind.LONGFORM,
                'publish_mode': PublishMode.REVIEW,
                'gates': [],
                'character_design_mode': CharacterDesignMode.AUTO,
                'voice_id': 'EXAVITQu4vr4xnSDxMaL',
                'stability': 0.5,
                'similarity_boost': 0.75,
                'wpm': 150,
                'default_budget_usd': '15.00',
                'is_active': True,
            },
        )
        action = 'Created' if ch_created else 'Updated'
        self.stdout.write(self.style.SUCCESS(f'  {action} channel: {channel}'))

        # NicheConfig
        factual_format = StoryFormat.objects.get(key='factual_documentary')
        NicheConfig.objects.update_or_create(
            channel=channel,
            defaults={
                'format': factual_format,
                'audience': (
                    'History enthusiasts aged 25–55, curious about ancient '
                    'civilisations, wars, and world-changing events. They are '
                    'intelligent, well-read, and will fact-check claims.'
                ),
                'angle': (
                    'Authoritative but accessible — revealing the untold details, '
                    'human stories, and systemic forces that mainstream history '
                    'glosses over.'
                ),
                'banned_topics': [
                    'modern partisan politics',
                    'conspiracy theories without scholarly evidence',
                    'unverified alternative history claims',
                ],
                'lore_document': _DEMO_CHANNEL_LORE,
            },
        )
        self.stdout.write(self.style.SUCCESS('  NicheConfig: seeded.'))

        # ChannelBranding
        ChannelBranding.objects.update_or_create(
            channel=channel,
            defaults={
                'watermark_position': 'bottom_right',
                'watermark_opacity': 0.5,
                'music_pool_tags': ['epic', 'orchestral', 'dramatic', 'historical', 'tense'],
                'thumbnail_palette': {
                    'primary': '#1A1A2E',
                    'secondary': '#16213E',
                    'accent': '#E94560',
                    'text': '#FFFFFF',
                    'text_shadow': '#000000',
                },
            },
        )
        self.stdout.write(self.style.SUCCESS('  ChannelBranding: seeded.'))

        # Character
        Character.objects.update_or_create(
            channel=channel,
            name='Dr. Marcus Webb',
            defaults={
                'status': CharacterStatus.APPROVED,
                'origin': CharacterOrigin.LIBRARY,
                'appearance_prompt': _DEMO_CHARACTER_APPEARANCE.strip(),
                'persona': _DEMO_CHARACTER_PERSONA.strip(),
                'total_creation_cost_usd': '0.0000',
                'hero_ref': None,
                'source_run': None,
            },
        )
        self.stdout.write(self.style.SUCCESS('  Character "Dr. Marcus Webb": seeded.'))

        # Topic ideas backlog
        niche_config = channel.niche_config
        topic_ideas: list[dict[str, Any]] = [
            {
                'title': 'The Fall of the Roman Empire',
                'topic': (
                    'Explore the political collapse, economic deterioration, military '
                    'overextension, and cultural fragmentation that ended the Western '
                    'Roman Empire in 476 AD — and why historians still debate the cause.'
                ),
                'score': 0.92,
            },
            {
                'title': 'The Manhattan Project: The Scientists Who Built the Bomb',
                'topic': (
                    'The inside story of the Manhattan Project — the brilliant, '
                    'conflicted physicists who raced to build the atomic bomb, the '
                    'moral crisis they faced, and the shadow they cast on the modern world.'
                ),
                'score': 0.88,
            },
            {
                'title': 'The Black Death: How the Plague Reshaped Medieval Europe',
                'topic': (
                    'How the bubonic plague of 1347–1353 killed a third of Europe, '
                    'shattered feudalism, launched the Renaissance, and permanently '
                    'altered the relationship between ordinary people and authority.'
                ),
                'score': 0.85,
            },
        ]

        for idea_data in topic_ideas:
            title = str(idea_data['title'])
            TopicIdea.objects.update_or_create(
                channel=channel,
                title=title,
                defaults={
                    'niche': niche_config,
                    'topic': idea_data['topic'],
                    'score': idea_data['score'],
                    'status': IdeaStatus.BACKLOG,
                    'metadata': {},
                },
            )
            self.stdout.write(
                self.style.SUCCESS(f'  TopicIdea: "{title[:60]}" seeded.'),
            )

        self.stdout.write(
            self.style.SUCCESS(
                '[4/4] Demo channel "History Explained (Demo)" fully seeded.\n'
                '      Channel · NicheConfig · ChannelBranding · Character · '
                f'{len(topic_ideas)} TopicIdeas',
            ),
        )
