from __future__ import annotations

from agents import Agent
from agents import Tool


def build_qa_agent() -> Agent:
    """Build the QA agent for quality assurance checks.

    TODO: Implement full QA tools for script and video quality checks.
    """

    @Tool(name="check_script_quality", description="Check script quality against standards.")
    def check_script_quality(script_text: str, word_count: int, hook_score: float) -> dict:
        """Placeholder: Check script quality.

        TODO: Implement actual script quality checks:
        - Hook effectiveness
        - Sentence length analysis
        - Pacing check
        - Fact-checking
        - SEO compliance
        """
        return {
            "passed": True,
            "score": 8.5,
            "issues": [],
            "recommendations": ["Mock recommendation"],
        }

    @Tool(name="check_video_quality", description="Check video quality against technical standards.")
    def check_video_quality(video_path: str) -> dict:
        """Placeholder: Check video quality.

        TODO: Implement actual video QA checks:
        - Audio sync check
        - Black frame detection
        - Duration validation
        - Resolution check
        - Subtitle accuracy
        - Music volume check
        """
        return {
            "passed": True,
            "checks_passed": 9,
            "checks_failed": 0,
            "issues": [],
        }

    return Agent(
        name="QAAgent",
        model="gpt-4o-mini",  # Use cheaper model for QA
        instructions="""
        You are a quality assurance specialist for YouTube content.

        SCRIPT QA:
        - Hook must score >= 7
        - Sentences must be < 20 words
        - All claims must be backed by facts
        - Active voice, second person ("you")

        VIDEO QA:
        - Audio must be in sync with video
        - No black frames
        - Duration must match target
        - Subtitles must be accurate
        - Music volume must be balanced

        OUTPUT: Return JSON with pass/fail status and detailed issues list.
        """,
        tools=[check_script_quality, check_video_quality],
    )
