from __future__ import annotations

from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver

from reelforge.research.models import TopicIdea


@receiver(post_save, sender=TopicIdea)
def sync_research_job_topic_counts(
    sender: type[TopicIdea],
    instance: TopicIdea,
    **kwargs: Any,
) -> None:
    """Keep ResearchJob topic counters in sync when a TopicIdea is approved or rejected."""
    instance.research_job.sync_topic_counts()
