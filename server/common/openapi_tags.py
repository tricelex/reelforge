"""OpenAPI tag names and descriptions for ReelForge API documentation."""

from typing import Final

from dmr.openapi.objects import Tag

AUTH: Final = 'Auth'
ENUMS: Final = 'Enums'
ANALYTICS: Final = 'Analytics'
CHANNELS: Final = 'Channels'
CHARACTERS: Final = 'Characters'
YOUTUBE: Final = 'YouTube'
ASSETS: Final = 'Assets'
PROMPTS: Final = 'Prompts'
IDEAS: Final = 'Ideas'
CHANNEL_RESEARCH: Final = 'Channel Research'
PIPELINE_RUNS: Final = 'Pipeline Runs'
PIPELINE_REVIEW: Final = 'Pipeline Review'
PIPELINE_CAST: Final = 'Pipeline Cast'
BLUEPRINTS: Final = 'Blueprints'
CLIPS: Final = 'Clips'
CLIP_CONFIG: Final = 'Clip Config'
CLIP_POSTS: Final = 'Clip Posts'
CAMPAIGNS: Final = 'Campaigns'
CLIP_SOURCES: Final = 'Clip Sources'

ALL_TAGS: Final = (
    AUTH,
    ENUMS,
    ANALYTICS,
    CHANNELS,
    CHARACTERS,
    YOUTUBE,
    ASSETS,
    PROMPTS,
    IDEAS,
    CHANNEL_RESEARCH,
    PIPELINE_RUNS,
    PIPELINE_REVIEW,
    PIPELINE_CAST,
    BLUEPRINTS,
    CLIPS,
    CLIP_CONFIG,
    CLIP_POSTS,
    CAMPAIGNS,
    CLIP_SOURCES,
)

TAG_DEFINITIONS: Final = (
    Tag(name=AUTH, description='JWT login, refresh, and current user.'),
    Tag(name=ENUMS, description='Shared enum registry for API clients.'),
    Tag(
        name=ANALYTICS,
        description='Dashboard metrics, run costs, and channel ROI.',
    ),
    Tag(
        name=CHANNELS,
        description='Channel configuration, branding, and niche settings.',
    ),
    Tag(
        name=CHARACTERS,
        description='AI character casting, sessions, and promotion.',
    ),
    Tag(
        name=YOUTUBE,
        description='YouTube OAuth connect, callback, and status.',
    ),
    Tag(
        name=ASSETS,
        description='Presigned uploads and library asset management.',
    ),
    Tag(
        name=PROMPTS,
        description='Prompt templates, versions, and story formats.',
    ),
    Tag(
        name=IDEAS,
        description='Topic ideation backlog and niche idea generation.',
    ),
    Tag(
        name=CHANNEL_RESEARCH,
        description=(
            'YouTube channel research jobs, dossiers, and ChannelSpec JSON.'
        ),
    ),
    Tag(
        name=PIPELINE_RUNS,
        description='Pipeline run lifecycle, gates, stages, and assets.',
    ),
    Tag(
        name=PIPELINE_REVIEW,
        description='Storyboard, scene breakdown, preview, and publish.',
    ),
    Tag(
        name=PIPELINE_CAST,
        description='Multi-character cast sessions within a run.',
    ),
    Tag(
        name=BLUEPRINTS,
        description='Pipeline blueprint definitions.',
    ),
    Tag(
        name=CLIPS,
        description='Clip candidate workflow, render, and preview.',
    ),
    Tag(
        name=CLIP_CONFIG,
        description='Layout, style, and timed overlay configuration.',
    ),
    Tag(
        name=CLIP_POSTS,
        description='Social post scheduling for clip candidates.',
    ),
    Tag(
        name=CAMPAIGNS,
        description='Clip campaigns and earnings tracking.',
    ),
    Tag(
        name=CLIP_SOURCES,
        description='Clip source registration and ingest probing.',
    ),
)
