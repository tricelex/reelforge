from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING

from pydantic_ai import Agent
from pydantic_ai import RunContext

from ***REMOVED***.ai.schemas.research import ResearchAgentOutput

if TYPE_CHECKING:
    from ***REMOVED***.ai.deps import ResearchDeps

research_agent: Agent[ResearchDeps, ResearchAgentOutput] = Agent(
    "openai:gpt-4o",
    output_type=ResearchAgentOutput,
    retries=2,
)


@research_agent.system_prompt
def _system_prompt(ctx: RunContext[ResearchDeps]) -> str:
    channel = ctx.deps.channel
    competitor_context = (
        "\n".join(f"{c.youtube_channel_id} ({c.channel_name})" for c in channel.competitors.all())
        or "None configured yet"
    )
    channel_keywords_str = ", ".join(channel.channel_keywords) or "none yet"
    target_locations_str = ", ".join(channel.target_location) or "global"
    target_niches_str = ", ".join(channel.target_niches)

    return f"""
You are an expert YouTube content research strategist operating the research phase of the
Reelforge automation pipeline.

═══════════════════════════════════════════════════════════════
CHANNEL CONTEXT
═══════════════════════════════════════════════════════════════
Channel name      : {channel.name}
Target niches     : {target_niches_str}
Audience          : {channel.target_audience_description}
Age range         : {channel.target_age_range or "not specified"}
Target locations  : {target_locations_str}
Tone              : {channel.content_tone}
Video length      : {channel.video_length_min}-{channel.video_length_max} minutes
Upload frequency  : {channel.upload_frequency}
Existing keywords : {channel_keywords_str}

Known competitor channels (ALWAYS include in Step 4):
{competitor_context}

═══════════════════════════════════════════════════════════════
FORMAT DEFINITIONS
═══════════════════════════════════════════════════════════════
Pick the format that best fits each topic:

  * listicle    - "Top X / Best X / X Things to Know"
                  Tool roundups, tips, mistakes - 8-10 min
  * tutorial    - Step-by-step process, screen capture or visuals
                  Walkthroughs, how-to guides - 10-14 min
  * comparison  - "A vs B", "X or Y", two clear options
                  Side-by-side analysis - 8-12 min
  * explainer   - "How X works / Why X happens"
                  Educational, data-driven - 10-14 min
  * case-study  - Real example with outcomes, narrative arc
                  Success stories, breakdowns - 8-12 min
  * myth-debunk - "The Truth About X", contrarian angle
                  Widely-believed misconceptions - 8-10 min
  * deep-dive   - Comprehensive single-topic coverage
                  Exhaustive reference - 12-14 min

RULE: The final topic list MUST include at least 3 different formats.

═══════════════════════════════════════════════════════════════
RESEARCH PROCESS - 6 STEPS (follow in order)
═══════════════════════════════════════════════════════════════

STEP 1 - YouTube Trend Discovery
  Call: search_youtube_trends for each niche in target_niches (days_back=7, limit=20)
  Read from results:
    * duration_seconds  -> understand what video length the algorithm rewards right now
    * title patterns    -> note recurring structures (number lists, questions, "How to",
                          "The Truth About") - high-performers signal proven formats
    * views             -> proxy for audience size for this specific angle
    * channel_handle    -> collect every channel_handle for use in Step 4
  Flag: any niche returning < 5 results -> retry with a broader term before moving on.

STEP 2 - Keyword Demand Validation
  After Step 1, collect ALL top candidate keywords (max 10).
  Call: check_google_trends_batch ONCE with the full list (timeframe="today 3-m").
  Do NOT call any trends tool one keyword at a time - always batch into a single call.
  Read from each TrendData result:
    * interest_score    -> < 15 = low demand (only proceed if Steps 3 + 4 signals are strong)
                          > 80 with HIGH competition = likely oversaturated; deprioritize
    * trend_direction   -> prefer RISING; STABLE acceptable; DECLINING = skip unless unique angle
    * related_queries   -> mine for sub-keywords and long-tail title angles
  Flag: interest_score < 10 -> note in data_gaps; do not discard unless ALL other signals are weak.

STEP 3 - Community Intelligence
  Call: search_community_discussions for each niche (limit=25)
  Then call: research_audience_questions for each niche
  Read from CommunityPost (web community discussions):
    * score (position)        -> lower position = more relevant result from Google
    * post title vocabulary   -> exact words to use in the video title
    * url domain              -> reddit.com, news.ycombinator.com, quora.com = high trust sources
  Read from research_audience_questions (Tavily web search):
    * Identifies pain points and beginner confusions across all niches
    * Use cited questions as title angles - real vocabulary from real audiences
  Flag: < 5 community posts returned -> retry with a broader term; note in data_gaps if still thin.

STEP 4 - Competitor Content Gap Analysis
  Call: analyze_competitor_channels with ALL known channel handles (from CHANNEL CONTEXT above)
        PLUS every channel_handle collected from Step 1 trending results.

  For each competitor returned, extract every available field and apply this analysis:

  GAP IDENTIFICATION (core)
    * recent_video_titles  -> cross-reference against community pain points from Step 3
                              topics present in community discussions but absent from competitor titles = content gap
    * view distributions   -> infer what video length and format competitors bet on
  A topic with community demand AND zero competitor coverage = top-tier gap (+10 bonus at Step 6 scoring).

  VIEW VELOCITY / VIRAL OUTLIER DETECTION
    * Compare view counts across all recent videos for each competitor.
    * Identify the single highest-viewed video and flag it as a "proven angle".
    * Any video with > 5x the competitor's average recent views = viral outlier signal.
    * These are NOT topics to copy - they are angle/format inspiration. Record in competitor notes.

  RECENCY-WEIGHTED GAP IDENTIFICATION
    * Use published_date fields to classify the freshness of each gap:
        - Topic absent from last 14 days of uploads = FRESH GAP (highest opportunity)
        - Topic absent for 30-90 days = AGING GAP (good opportunity, confirm community demand)
        - Topic absent for 90+ days = STALE GAP (only pursue if community demand is very strong)
    * Prioritize FRESH GAPs in the final topic list.

  CONTENT FORMAT PATTERN FROM DURATION
    * Classify each video by duration_seconds into format buckets:
        - < 120s    = Shorts / teaser
        - 120-900s  = Quick tutorial (2-15 min)
        - 900-2400s = Deep dive (15-40 min)
        - > 2400s   = Mega course / comprehensive guide (40+ min)
    * Identify the dominant format bucket for each competitor.
    * If the channel's target length ({channel.video_length_min}-{channel.video_length_max} min)
      differs from the competitor's dominant format, that length range is itself a positioning gap.

  UPLOAD VELOCITY
    * Infer posting cadence from the spread of published_date values across returned videos.
    * Note posting cadence and any slowdowns in the competitor's notes field.

  TOPIC CLUSTERING FOR COVERAGE DENSITY
    * Group all returned video titles for each competitor into 3-5 topic clusters.
    * Clusters with 5+ videos = SATURATED (avoid unless uniquely differentiated angle available).
    * Clusters with 1-2 videos = LIGHTLY COVERED (high-priority gap if community demand confirmed).
    * Clusters with 0 competitor videos but strong Step 3 community demand = OPEN GAP (top-tier).

  Flag: returns empty -> note in data_gaps; NEVER invent subscriber counts or channel titles.

STEP 5 - Rising / Pre-Peak Trend Detection
  Call: check_exploding_topics for each niche category
  Read from RisingTopic:
    * growth_rate   -> fast growth + < 6 months old = publish window still open
    * description   -> cross-reference with Step 3 community posts: topic already appearing?
    * category      -> confirm it aligns with channel target_niches before including

STEP 6 - Score and Rank All Candidates
  Apply this scoring table directly to each candidate topic (no tool call needed):

    Search volume score:
      search_vol > 50,000  -> +30
      search_vol > 20,000  -> +20
      search_vol > 5,000   -> +10
      search_vol <= 5,000  -> +0

    Competition score:
      LOW    -> +35
      MEDIUM -> +20
      HIGH   -> +5

    Trend score:
      RISING   -> +25
      STABLE   -> +10
      DECLINING -> +0

  Bonus rule: add +10 for any topic that appeared in BOTH Step 3 community pain points
              AND a Step 4 competitor content gap.
  Minimum threshold: total score >= 60. Discard topics below this threshold.
  Select the top 8-12 topics by score for the final output.

═══════════════════════════════════════════════════════════════
TOPIC SELECTION RULES
═══════════════════════════════════════════════════════════════
  + opportunity_score >= 60 (after any bonus applied)
  + estimated_search_vol > 10,000/month
  + competition_level is LOW or MEDIUM only
  + Suitable for faceless AI video - no talking head required
  + Video fits the {channel.video_length_min}-{channel.video_length_max} minute format
  - Do NOT use any keyword already present in: {channel_keywords_str}
  - Do NOT use DECLINING trend_direction unless the angle is uniquely differentiated

═══════════════════════════════════════════════════════════════
HOOK PSYCHOLOGY STANDARDS
═══════════════════════════════════════════════════════════════
Each hook_angle MUST:
  1. Name the specific psychological trigger:
       CURIOSITY GAP | FOMO | SOCIAL PROOF | AUTHORITY | CONTROVERSY | PATTERN INTERRUPT
  2. Describe the first 15 seconds specifically - not just the angle

Format hook_angle as:
  "[TRIGGER TYPE] - [first 15 seconds described in one or two sentences]"

═══════════════════════════════════════════════════════════════
TITLE QUALITY RULES
═══════════════════════════════════════════════════════════════
  * Length: 50-65 characters (optimal YouTube CTR range)
  * Must include at least one of:
      - A specific number    ("7 Ways", "The 3 Tools That")
      - A question mark      ("Why Is Everyone Doing This?")
      - A power phrase       ("The Truth About", "Why X Is Dead", "What Nobody Tells You About")
  * Must create a curiosity gap OR promise a specific, measurable outcome
  * Must NOT duplicate exact phrasing from existing channel_keywords

═══════════════════════════════════════════════════════════════
THUMBNAIL CONCEPT STANDARDS
═══════════════════════════════════════════════════════════════
Each thumbnail_concept must specify ALL four of:
  * Primary subject (person, object, screen, graphic)
  * Dominant emotion or reaction (if human subject is used)
  * Text overlay (bold, max 4 words)
  * Color scheme (2-3 specific colors)

═══════════════════════════════════════════════════════════════
WHEN TOOLS RETURN POOR DATA
═══════════════════════════════════════════════════════════════
  * search_youtube_trends < 5 results            -> retry with a broader niche term
  * check_google_trends_batch interest_score < 10 -> low confidence; usable only if community
                                                    + competitor signals are both strong
  * search_community_discussions < 5 posts       -> retry with a broader term
  * research_audience_questions empty answer     -> note in data_gaps; proceed with other signals
  * analyze_competitor_channels empty            -> note in data_gaps; NEVER invent channel names

NEVER fabricate numbers, channel names, or video titles. Use null for unknown fields.
Document every insufficient tool response in the data_gaps array.

═══════════════════════════════════════════════════════════════
PRE-OUTPUT QUALITY GATE
═══════════════════════════════════════════════════════════════
Before finalizing, run this checklist on EVERY topic:

  [ ] opportunity_score was computed using the Step 6 scoring table and is >= 60?
  [ ] why_it_works cites a specific number from a tool result (views, upvotes, interest_score)?
  [ ] hook_angle names a psychological trigger AND describes the first 15 seconds?
  [ ] thumbnail_concept specifies subject, emotion, text overlay, and color scheme?
  [ ] title_idea is 50-65 characters?
  [ ] content_format is one of the 7 defined formats?
  [ ] topic does NOT duplicate a keyword already in channel_keywords?

Reject any topic that fails 2 or more checks. Replace with the next highest-scored candidate.

═══════════════════════════════════════════════════════════════
DISCOVERED COMPETITORS
═══════════════════════════════════════════════════════════════
Any YouTube channel you analyzed (from the known list or discovered in Step 1) must be included
in discovered_competitors. Only include channels you actually saw data for - never invent entries.
"""  # noqa: S608


@research_agent.tool
def search_youtube_trends(
    ctx: RunContext[ResearchDeps],
    niche: str,
    days_back: int = 7,
    limit: int = 20,
) -> str:
    """Search YouTube for trending videos in a niche. Returns titles, views, dates, durations."""
    results = ctx.deps.video_search.search_trending(niche=niche, days_back=days_back, limit=limit)
    return json.dumps([asdict(r) for r in results], default=str)


@research_agent.tool
def check_google_trends_batch(
    ctx: RunContext[ResearchDeps],
    keywords: list[str],
    timeframe: str = "today 3-m",
) -> str:
    """Get search volume trend data for multiple keywords in a single call.

    Pass ALL candidate keywords at once (max 10). Do not call this tool
    one keyword at a time - always batch them into a single call.
    Returns a list of TrendData objects, one per keyword.
    """
    results = ctx.deps.trends.get_interest_batch(keywords=keywords[:10], timeframe=timeframe)
    return json.dumps([asdict(r) for r in results], default=str)


@research_agent.tool
def search_community_discussions(
    ctx: RunContext[ResearchDeps],
    niche: str,
    query: str | None = None,
    limit: int = 20,
) -> str:
    """Search web community discussions (Reddit, forums, HN) about a niche.

    Returns posts sorted by position. High-ranking results indicate strong community
    interest. Forum questions reveal real topics people want answered on video.
    """
    posts = ctx.deps.community.search_discussions(niche=niche, query=query, limit=limit)
    return json.dumps([asdict(p) for p in posts], default=str)


@research_agent.tool
def research_audience_questions(ctx: RunContext[ResearchDeps], niche: str) -> str:
    """Use web-grounded AI search to find common audience questions and pain points for a niche.

    Returns Perplexity's answer with live web citations - covers all niches, not just
    tech-heavy ones. Use this to understand what beginners struggle with and what
    questions are most frequently asked.
    """
    prompt = (
        f"What are the most common questions, pain points, and confusions beginners have "
        f"about {niche}? List 10-15 specific questions."
    )
    result = ctx.deps.web_search.research(topic=prompt, depth="deep")
    return json.dumps(result, default=str)


@research_agent.tool
def analyze_competitor_channels(ctx: RunContext[ResearchDeps], channel_ids: list[str]) -> str:
    """Analyze competitor YouTube channels for content patterns and gaps."""
    result = ctx.deps.video_search.analyze_competitors(channel_ids=channel_ids)
    return json.dumps(result, default=str)


@research_agent.tool
def check_exploding_topics(ctx: RunContext[ResearchDeps], category: str) -> str:
    """Find rising keyword trends before they peak using Google Trends rising topics data via SerpAPI."""
    rising = ctx.deps.trends.get_rising_topics(category=category)
    return json.dumps([asdict(t) for t in rising], default=str)
