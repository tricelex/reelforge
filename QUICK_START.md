# Quick Start Guide - Testing Pipeline Models

## Start the Environment

```bash
# Start all Docker containers
just up

# Verify everything is running
just ps
```

## Access the Admin

1. Create superuser (if needed):
```bash
just create-superuser
```

2. Open browser to: http://localhost:8000/admin/

3. Navigate the new sections:
   - **Channel Management** → Channels, Competitors, Playlists
   - **Pipeline** → Pipeline Runs, Pipeline Events
   - **Content Production** → All 6 stage job types
   - **Analytics** → Analytics Snapshots

## Test Model Creation

### Option 1: Via Django Admin (Recommended)

1. Go to **Channel Management** → **Channels**
2. Click **Add Channel**
3. Fill in:
   - Name: "My Test Channel"
   - Slug: "my-test-channel"
   - Niche Category: Finance
   - Status: Setup
4. Save

You'll see the channel with:
- Colored status badge
- Competitor and Playlist inlines
- All configuration sections organized in fieldsets

### Option 2: Via Django Shell

```bash
just manage shell
```

```python
from ***REMOVED***.channels.models import Channel
from ***REMOVED***.research.models import ResearchJob, TopicIdea
from ***REMOVED***.pipeline.models import PipelineRun

# Create a channel
channel = Channel.objects.create(
    name="Finance Tips Channel",
    slug="finance-tips",
    niche_category="FINANCE",
    youtube_handle="financetips",
    content_tone="conversational_authoritative",
    video_length_min=8,
    video_length_max=12,
)
print(f"✓ Created: {channel}")

# Create a research job
research = ResearchJob.objects.create(
    channel=channel,
    search_keywords=["personal finance", "money tips", "budgeting"],
    min_search_volume=1000,
)
print(f"✓ Created: {research}")
print(f"  Status: {research.status}")
print(f"  Available transitions: {research.available_transitions}")

# Create a topic idea
topic = TopicIdea.objects.create(
    channel=channel,
    research_job=research,
    title_idea="10 Money Mistakes to Avoid in Your 20s",
    description="Common financial mistakes young adults make and how to avoid them",
    keywords=["money mistakes", "personal finance", "financial advice"],
    estimated_search_volume=5000,
    competition_level="MEDIUM",
    trend_direction="RISING",
    trend_score=8.5,
    gap_opportunity_score=7.2,
)
print(f"✓ Created: {topic}")
print(f"  Combined score: {topic.combined_score}/10")

# Create a pipeline run
pipeline = PipelineRun.objects.create(
    channel=channel,
    research_job=research,
    topic=topic,
)
print(f"✓ Created: {pipeline}")
print(f"  Status: {pipeline.overall_status}")
print(f"  Available transitions: {pipeline.available_transitions}")

# Test FSM transition
pipeline.begin_research()
pipeline.save()
print(f"✓ Transitioned to: {pipeline.overall_status}")
print(f"  New transitions: {pipeline.available_transitions}")
```

## Verify FSM State Management

```python
from ***REMOVED***.research.models import ResearchJob
from django_fsm import TransitionNotAllowed

job = ResearchJob.objects.first()

# Valid transition
job.start()
job.save()
print(f"Status: {job.status}")  # RUNNING

# Try invalid transition (should fail)
try:
    job.start()  # Can't start when already running
    job.save()
except TransitionNotAllowed as e:
    print(f"✓ FSM protection working: {e}")

# Valid transitions from RUNNING
print(f"Available: {job.available_transitions}")
# Should show: ['complete', 'fail', 'pause', 'reject']
```

## Check Admin Features

### Status Badges
1. Go to **Research Jobs**
2. Create a few jobs with different statuses
3. See color-coded badges:
   - PENDING → Grey
   - RUNNING → Blue
   - COMPLETED → Green
   - FAILED → Red

### Inlines
1. Edit a **Channel**
2. Add competitors in the inline table
3. Add playlists in the inline table
4. Save and verify they persist

### Filters
1. Go to **Topic Ideas**
2. Use filters:
   - Status
   - Approved/Not Approved
   - Trend Direction
   - Competition Level
3. Verify filtering works

### Search
1. Go to **Script Jobs**
2. Search by:
   - Final title
   - Topic title
   - Channel name
3. Verify results

## Verify Relationships

```python
from ***REMOVED***.channels.models import Channel

channel = Channel.objects.first()

# Check reverse relationships
print(f"Research jobs: {channel.research_jobs.count()}")
print(f"Topic ideas: {channel.topic_ideas.count()}")
print(f"Pipeline runs: {channel.pipeline_runs.count()}")

# Navigate relationships
pipeline = channel.pipeline_runs.first()
if pipeline:
    print(f"Pipeline → Channel: {pipeline.channel.name}")
    print(f"Pipeline → Topic: {pipeline.topic.title_idea if pipeline.topic else 'None'}")
    print(f"Pipeline events: {pipeline.events.count()}")
```

## Check Computed Properties

```python
from ***REMOVED***.research.models import ResearchJob, TopicIdea

# ResearchJob approval rate
job = ResearchJob.objects.first()
job.topics_discovered = 10
job.topics_approved = 7
job.save()
print(f"Approval rate: {job.approval_rate}%")  # 70.0%

# TopicIdea combined score
topic = TopicIdea.objects.first()
topic.trend_score = 8.5
topic.gap_opportunity_score = 7.5
topic.save()
print(f"Combined score: {topic.combined_score}/10")  # 8.0
```

## Test File Uploads

```python
from ***REMOVED***.channels.models import Channel
from django.core.files.uploadedfile import SimpleUploadedFile

channel = Channel.objects.first()

# Simulate logo upload
logo_file = SimpleUploadedFile(
    "logo.png",
    b"fake image content",
    content_type="image/png"
)
channel.logo_file = logo_file
channel.save()

print(f"Logo uploaded to: {channel.logo_file.name}")
```

## Explore PipelineEvent Audit Log

```python
from ***REMOVED***.pipeline.models import PipelineRun, PipelineEvent

pipeline = PipelineRun.objects.first()

# Create some events
PipelineEvent.objects.create(
    pipeline_run=pipeline,
    event_type="INFO",
    event_name="Pipeline Started",
    message="Pipeline run initialized by operator",
    metadata={"source": "manual"},
)

PipelineEvent.objects.create(
    pipeline_run=pipeline,
    event_type="SUCCESS",
    event_name="Research Complete",
    message="Research job completed successfully",
    triggered_by_agent="ResearchAgent",
    metadata={"topics_found": 5},
)

# View all events
for event in pipeline.events.all():
    print(f"[{event.event_type}] {event.event_name}: {event.message}")
```

## Performance Check

```python
from django.db import connection
from django.test.utils import CaptureQueriesContext

from ***REMOVED***.channels.models import Channel

# Check query count for optimized list views
with CaptureQueriesContext(connection) as ctx:
    channels = list(Channel.objects.all()[:10])
    print(f"Channels query count: {len(ctx.captured_queries)}")

# Should be 1 query (no N+1 problems)
```

## Troubleshooting

### If admin doesn't load:
```bash
just manage check
just manage check admin
```

### If migrations fail:
```bash
just manage showmigrations
just manage migrate --fake-initial
```

### If autocomplete doesn't work:
Ensure the related model has `search_fields` defined in its admin.

### To reset database:
```bash
just down
just prune  # Removes volumes
just up
just manage migrate
```

## Code Quality

Run checks before committing:

```bash
# All pre-commit hooks
just precommit

# Or individually
just lint       # Ruff linting
just format     # Ruff formatting
just typecheck  # mypy
```

## What to Test

- [ ] Create a Channel via admin
- [ ] Add Competitors inline
- [ ] Add Playlists inline
- [ ] Create a ResearchJob
- [ ] Create TopicIdeas
- [ ] Create a PipelineRun
- [ ] Test FSM transitions
- [ ] View status badges (different colors)
- [ ] Test list filters
- [ ] Test search functionality
- [ ] Create PipelineEvents
- [ ] Verify events inline is read-only
- [ ] Navigate through foreign key relationships
- [ ] Check computed properties display
- [ ] Verify cost tracking fields

## Next Steps

Once you've verified the models work:

1. **Phase 2**: Implement provider registry (`services/providers/`)
2. **Phase 3**: Add Celery tasks for async processing
3. **Phase 4**: Integrate OpenAI Agents SDK
4. **Phase 5+**: Build service layers for each pipeline stage

---

**All models are production-ready and waiting for business logic!** ✅
