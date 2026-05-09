# Reelforge Clipping — Frontend Design Mockups

## Context

The Reelforge clipping feature needs a Next.js frontend (separate repo) that consumes the clipping
REST API documented in `docs/clipping-api-flow.md`. This document provides detailed, screen-by-screen
ASCII wireframe mockups for the entire clipping workflow, from job creation through post analytics.

The app is an **internal operator tool designed to customer-facing quality standards**.

**Tech stack decided:**
- Framework: Next.js (App Router)
- Components: shadcn/ui (Radix primitives + Tailwind CSS)
- Theme: dark + light mode toggle
- Navigation: fixed left sidebar
- Real-time: SSE (`EventSource`) with REST polling fallback
- API base: `/api/v1/`

---

## 0. Design System

### Color Tokens (dark / light, shadcn defaults)

| Token | Dark | Light | Usage |
|-------|------|-------|-------|
| `background` | `hsl(224 71% 4%)` | `hsl(0 0% 100%)` | Page bg |
| `card` | `hsl(224 71% 8%)` | `hsl(0 0% 98%)` | Card/panel bg |
| `muted` | `hsl(215 20% 65%)` | `hsl(215 20% 45%)` | Secondary text |
| `primary` | `hsl(217 91% 60%)` | `hsl(217 91% 50%)` | CTAs, links |
| `destructive` | `hsl(0 72% 51%)` | `hsl(0 72% 45%)` | Reject, delete, error |
| `border` | `hsl(215 20% 20%)` | `hsl(215 20% 88%)` | Dividers |

### Status Badge Color Map

| Status | Color | Icon | Animated? |
|--------|-------|------|-----------|
| `INITIALIZING` | grey | ○ | no |
| `DOWNLOADING` | blue | ⟳ | pulse |
| `TRANSCRIBING` | indigo | ⟳ | pulse |
| `ANALYZING` | purple | ⟳ | pulse |
| `AWAITING_CLIP_APPROVAL` | amber | ● | no |
| `RENDERING` | blue | ⟳ | pulse |
| `PAUSED_AT_GATE` | amber | ⏸ | blink |
| `DISTRIBUTING` | cyan | ⟳ | pulse |
| `COMPLETED` / `RENDERED` / `DISTRIBUTED` | green | ✓ | no |
| `FAILED` | red | ✗ | no |
| `PROPOSED` | slate | ○ | no |
| `APPROVED` | green | ✓ | no |
| `REJECTED` | red strikethrough | ✗ | no |
| `PAUSED` | amber | ⏸ | no |

### Typography
- Font: Geist Sans (Next.js default) or Inter
- Page titles: `text-xl font-semibold tracking-tight`
- Section headers: `text-sm font-medium text-muted-foreground uppercase tracking-wide`
- Body: `text-sm`
- Code / IDs / timestamps: Geist Mono `font-mono text-xs`

### Key shadcn/ui Components
`Button` · `Badge` · `Card` · `Table` · `Dialog` · `Tabs` · `Progress` · `Separator`
`ScrollArea` · `Sheet` · `DropdownMenu` · `Select` · `Input` · `Textarea` · `Label`
`Switch` · `Slider` · `Checkbox` · `Skeleton` · `Alert` · `Toast` · `Breadcrumb`
`Tooltip` · `Collapsible`

---

## 1. App Shell

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              APP SHELL (100vw × 100vh)                          │
│                                                                                 │
│  ┌──────────────────┐  ┌───────────────────────────────────────────────────┐   │
│  │  SIDEBAR (240px) │  │  HEADER (sticky, 56px, border-b)                 │   │
│  │  fixed, h-screen │  │  ┌─────────────────────────┐  ┌────────────────┐ │   │
│  │                  │  │  │  ≡  Breadcrumb path      │  │ 🔔  👤 Operat │ │   │
│  │  ┌────────────┐  │  │  └─────────────────────────┘  └────────────────┘ │   │
│  │  │ [RF] Reel- │  │  └───────────────────────────────────────────────────┘   │
│  │  │    forge   │  │  ┌───────────────────────────────────────────────────┐   │
│  │  └────────────┘  │  │                                                   │   │
│  │  (logo + wordmark│  │  MAIN CONTENT AREA (scrollable, p-6)              │   │
│  │   top of sidebar)│  │                                                   │   │
│  │                  │  │  ← page-specific content renders here →           │   │
│  │  ─── MAIN ────   │  │                                                   │   │
│  │  ○  Dashboard    │  │                                                   │   │
│  │  ●  Clipping  ▾  │  │                                                   │   │
│  │     All Jobs     │  │                                                   │   │
│  │     New Job      │  │                                                   │   │
│  │                  │  │                                                   │   │
│  │  ─ LIBRARY ────  │  │                                                   │   │
│  │  ○  Media Assets │  │                                                   │   │
│  │  ○  Music        │  │                                                   │   │
│  │  ○  Templates    │  │                                                   │   │
│  │                  │  │                                                   │   │
│  │  ─ SETTINGS ───  │  │                                                   │   │
│  │  ○  Settings     │  │                                                   │   │
│  │                  │  │                                                   │   │
│  │  ─────────────── │  │                                                   │   │
│  │  [☀ / ☾] theme   │  │                                                   │   │
│  └──────────────────┘  └───────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Implementation notes:**
- Sidebar: `<aside className="w-[240px] shrink-0 border-r h-screen sticky top-0 flex flex-col">`
- Active nav item: `bg-accent text-accent-foreground rounded-md`
- Clipping section is a `<Collapsible>` that expands to show sub-items
- Theme toggle: shadcn `<Switch>` or icon button at sidebar bottom using `next-themes`
- Header breadcrumb: shadcn `<Breadcrumb>` — path reflects current route
- `[+ New Job]` button appears in header when on any clipping route

---

## 2. Job List Page

**Route:** `/clipping/jobs`
**API:** `GET /api/v1/clipping/jobs/`

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Clipping Jobs                                          [+ New Job]           │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │  FILTER BAR                                                           │   │
│  │  [All Status ▾]  [All Sources ▾]  [Date Range ▾]  [🔍 Search...  ]   │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │  TABLE                                                                │   │
│  │  ┌────────────────────────┬───────────────────┬──────┬──────┬──────┐ │   │
│  │  │ Job                    │ Status            │Source│Clips │ Age  │ │   │
│  │  ├────────────────────────┼───────────────────┼──────┼──────┼──────┤ │   │
│  │  │ How to grow on YouTube │ ● Awaiting Apprvl │  YT  │ 5/8  │ 2h   │ │   │
│  │  │ yt:dQw4w9WgXcQ         │                   │      │apprvd│      │ │   │
│  │  │                        │                   │      │      │[View]│ │   │
│  │  ├────────────────────────┼───────────────────┼──────┼──────┼──────┤ │   │
│  │  │ Brand review deep dive │ ⟳ Rendering       │ URL  │ 3/3  │ 5h   │ │   │
│  │  │ cdn.example.com/...    │                   │      │rndg  │[View]│ │   │
│  │  ├────────────────────────┼───────────────────┼──────┼──────┼──────┤ │   │
│  │  │ Q1 recap video         │ ✓ Completed       │  UP  │ 6/6  │ 1d   │ │   │
│  │  │ q1-recap.mp4           │                   │      │      │[View]│ │   │
│  │  ├────────────────────────┼───────────────────┼──────┼──────┼──────┤ │   │
│  │  │ Product launch video   │ ⟳ Transcribing    │  YT  │  —   │ 10m  │ │   │
│  │  │ yt:abc123              │                   │      │      │[View]│ │   │
│  │  ├────────────────────────┼───────────────────┼──────┼──────┼──────┤ │   │
│  │  │ Office tour            │ ✗ Failed           │  YT  │  —   │ 2d   │ │   │
│  │  │ yt:xyz789              │                   │      │      │[Retry│ │   │
│  │  │                        │                   │      │      │ View]│ │   │
│  │  └────────────────────────┴───────────────────┴──────┴──────┴──────┘ │   │
│  │                                                                        │   │
│  │  Showing 5 of 24 jobs                  [← Prev]  1  2  3  [Next →]   │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
│  EMPTY STATE (no jobs yet):                                                   │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │                        📹                                             │   │
│  │              No clipping jobs yet                                     │   │
│  │     Add a YouTube link, direct URL, or upload a video file           │   │
│  │              to start generating short clips.                         │   │
│  │                     [+ Create Your First Job]                        │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Source badges:** YT = YouTube · URL = Direct URL · UP = Upload
**Row click** → navigates to `/clipping/jobs/[id]`
**⋮ row menu:** View · Pause/Resume · Retry (if FAILED) · Delete (with confirm dialog)

---

## 3. Create Job — Dialog (Modal)

**Trigger:** `[+ New Job]` from sidebar, header, or job list
**API:** `POST /api/v1/clipping/jobs/`

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  DIALOG (max-w-lg, centered)                                    [✕]   │  │
│  │  ──────────────────────────────────────────────────────────────────   │  │
│  │  Create Clipping Job                                                  │  │
│  │  Add a video to start generating short-form clips.                    │  │
│  │                                                                       │  │
│  │  Source Type                                                          │  │
│  │  ┌───────────────────────────────────────────────────────────────┐   │  │
│  │  │  ● YouTube URL    ○ Direct URL    ○ Upload File               │   │  │
│  │  └───────────────────────────────────────────────────────────────┘   │  │
│  │                                                                       │  │
│  │  ── YOUTUBE URL VARIANT ─────────────────────────────────────────    │  │
│  │  YouTube URL *                                                        │  │
│  │  ┌───────────────────────────────────────────────────────────────┐   │  │
│  │  │  https://www.youtube.com/watch?v=...                          │   │  │
│  │  └───────────────────────────────────────────────────────────────┘   │  │
│  │                                                                       │  │
│  │  ── UPLOAD VARIANT (shown instead when Upload selected) ──────────   │  │
│  │  ┌───────────────────────────────────────────────────────────────┐   │  │
│  │  │                     ⬆                                         │   │  │
│  │  │         Drop video file here, or click to browse              │   │  │
│  │  │         MP4, MOV, MKV · Max 4 GB                              │   │  │
│  │  │                    [Browse Files]                              │   │  │
│  │  └───────────────────────────────────────────────────────────────┘   │  │
│  │  upload-progress.mp4 (87.2 MB) ████████████░░░░░  62%  (uploading)  │  │
│  │                                                                       │  │
│  │  ── SHARED FIELDS ────────────────────────────────────────────────   │  │
│  │  Job Title  (optional — uses video title if blank)                   │  │
│  │  ┌───────────────────────────────────────────────────────────────┐   │  │
│  │  │                                                               │   │  │
│  │  └───────────────────────────────────────────────────────────────┘   │  │
│  │                                                                       │  │
│  │  Clips to Generate                                                    │  │
│  │  ┌──────┐                                                             │  │
│  │  │  5   │  ●──────────────────────  (slider, 1–15)                   │  │
│  │  └──────┘                                                             │  │
│  │                                                                       │  │
│  │  ──────────────────────────────────────────────────────────────────  │  │
│  │                                    [Cancel]   [Create Job →]         │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

**After submit:** dialog closes, user is navigated to `/clipping/jobs/[newId]` which shows
the pipeline progress page in INITIALIZING/DOWNLOADING state.

---

## 4. Job Detail — Pipeline Progress

**Route:** `/clipping/jobs/[jobId]`
**API:** `GET /api/v1/clipping/jobs/{id}/` + SSE `GET /api/v1/clipping/jobs/{id}/stream/`

This page has two major phases that share the same URL:
- **Phase A** (INITIALIZING → DOWNLOADING → TRANSCRIBING → ANALYZING): progress view
- **Phase B** (AWAITING_CLIP_APPROVAL → RENDERING → COMPLETED): candidates view (Section 5 & 8)

### Phase A — Pipeline in Progress

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ← Jobs                                                          [⋮]         │
│  How to grow on YouTube in 2025                                               │
│  youtube.com/watch?v=dQw4w9WgXcQ  ·  Created 10 min ago                     │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                               │
│  PIPELINE STAGE TRACKER                                                       │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │                                                                       │   │
│  │   ✓ Download    ──────────────────●──────────────  ⟳ Transcribe      │   │
│  │                                 (active)                              │   │
│  │      ○  Analyze           ○  Awaiting Approval                       │   │
│  │                                                                       │   │
│  │   ┌──────────────────────────────────────────────────────────────┐   │   │
│  │   │   ⟳  Transcribing audio...                                  │   │   │
│  │   │   Sending to Whisper API · Started 2 min ago                │   │   │
│  │   │                                                              │   │   │
│  │   │   ████████████████░░░░░░░░░░░░  ~55%  (estimated)           │   │   │
│  │   └──────────────────────────────────────────────────────────────┘   │   │
│  │                                                                       │   │
│  │   Source: youtube.com/watch?v=dQw4w9WgXcQ                            │   │
│  │   Duration: 24:37  ·  File size: 87.2 MB  ·  Downloaded: ✓           │   │
│  │   Clips requested: 5                                                  │   │
│  │                                                                       │   │
│  │   ⟳ Live  ·  Auto-updating via SSE                [Pause Updates]    │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Phase A — ANALYZING state

```
│  ✓ Download   ✓ Transcribe   ──────●──────  ⟳ Analyze   ○  Review           │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │   ⟳  AI is analyzing your video...                                  │    │
│  │   Identifying the best moments for short-form clips                  │    │
│  │                                                                      │    │
│  │   ●  Transcript loaded (12,482 words)                               │    │
│  │   ⟳  Running clip candidate analysis...                             │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
```

### Phase A — FAILED state

```
│  ✓ Download   ✗ Transcribe   ○  Analyze   ○  Review                         │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │   ✗  Transcription failed                                           │    │
│  │   ────────────────────────────────────────────────────────────────  │    │
│  │   OpenAI API error: Rate limit exceeded. Retried 3 times.          │    │
│  │   Failed at: 2026-05-09 14:32 UTC                                  │    │
│  │                                                                      │    │
│  │                              [↩ Retry from Transcription]           │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  Note: if failed during ANALYZING, button reads "Retry from Analysis"        │
```

### Phase A — SSE fallback banner (connection lost)

```
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  ⚠ Live updates disconnected. Polling every 5 s.          [Reconnect]  │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
```

---

## 5. Candidate Review

**Route:** `/clipping/jobs/[jobId]` (same URL — page reveals candidates when job reaches
`AWAITING_CLIP_APPROVAL`)
**API:** `GET /api/v1/clipping/candidates/?job={id}`

### Phase B — Awaiting Approval

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ← Jobs                                                          [⋮]         │
│  How to grow on YouTube in 2025                                               │
│  ● Awaiting Clip Approval  ·  8 candidates generated  ·  24:37 source        │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │  ACTION BAR                                                           │   │
│  │  [✓ Approve All (8)]    Filter: [All ▾]   5 approved · 1 rejected    │   │
│  │                                              [▶ Start Rendering]     │   │
│  │  (Start Rendering is disabled until ≥1 approved;                     │   │
│  │   tooltip: "Approve at least one candidate to continue")             │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
│  CANDIDATE GRID (2-col desktop, 1-col mobile)                                │
│  ┌─────────────────────────────┐   ┌─────────────────────────────┐          │
│  │  PROPOSED CARD              │   │  PROPOSED CARD              │          │
│  │  ──────────────────────     │   │  ──────────────────────     │          │
│  │  ┌─────────────────────┐   │   │  ┌─────────────────────┐   │          │
│  │  │   [VIDEO THUMB]     │   │   │  │   [VIDEO THUMB]     │   │          │
│  │  │   9:16 aspect ratio │   │   │  │   9:16 aspect ratio │   │          │
│  │  │   0:00 ─────── 0:45 │   │   │  │   1:32 ────── 2:10  │   │          │
│  │  └─────────────────────┘   │   │  └─────────────────────┘   │          │
│  │                             │   │                             │          │
│  │  "The biggest mistake       │   │  "3 things YouTube          │          │
│  │   creators make in..."      │   │   never tells you..."       │          │
│  │                             │   │                             │          │
│  │  0:00 → 0:45  (45 s)        │   │  1:32 → 2:10  (38 s)        │          │
│  │  ★★★★☆  0.87 relevance      │   │  ★★★☆☆  0.71 relevance      │          │
│  │                             │   │                             │          │
│  │  [✓ Approve] [✗ Reject]    │   │  [✓ Approve] [✗ Reject]    │          │
│  │  [⚙ Configure]             │   │  [⚙ Configure]             │          │
│  └─────────────────────────────┘   └─────────────────────────────┘          │
│                                                                               │
│  ┌─────────────────────────────┐   ┌─────────────────────────────┐          │
│  │  APPROVED CARD              │   │  REJECTED CARD              │          │
│  │  ──────────────────────     │   │  ──────────────────────     │          │
│  │  ┌─────────────────────┐   │   │  ┌─────────────────────┐   │          │
│  │  │   [VIDEO THUMB]     │   │   │  │   [VIDEO THUMB]     │   │          │
│  │  │   (full opacity)    │   │   │  │   (40% opacity,     │   │          │
│  │  │   green border ring │   │   │  │    greyscale filter, │   │          │
│  │  └─────────────────────┘   │   │  │    red border ring) │   │          │
│  │                             │   │  └─────────────────────┘   │          │
│  │  "Going viral in 2025..."   │   │                             │          │
│  │                             │   │  ~~"Why most channels      │          │
│  │  ✓ APPROVED                 │   │    quit before 1k..."~~    │          │
│  │                             │   │  ✗ REJECTED                 │          │
│  │  [✗ Undo Approve]          │   │  "Too slow, no value"       │          │
│  │  [⚙ Configure]             │   │  [↩ Undo Reject]           │          │
│  └─────────────────────────────┘   └─────────────────────────────┘          │
│                                                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │  STICKY FOOTER (bottom of page, appears once ≥1 approved)            │   │
│  │  5 approved  ·  1 rejected  ·  2 pending review                      │   │
│  │                                        [▶ Start Rendering (5 clips)] │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Reject confirmation inline:** clicking `[✗ Reject]` shows an inline reason field:
```
│  ┌───────────────────────────────────────────────┐
│  │  Rejection reason (optional)                  │
│  │  [Too slow, no real value here            ]   │
│  │                     [Cancel]  [Confirm Reject]│
│  └───────────────────────────────────────────────┘
```

---

## 6. Candidate Configuration Page

**Route:** `/clipping/jobs/[jobId]/candidates/[candidateId]`
**API:** `GET /api/v1/clipping/candidates/{id}/` (includes nested layout + style config IDs)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ← Back to Job: How to grow on YouTube                                       │
│  Candidate: "The biggest mistake creators make..."                            │
│  ● APPROVED · 0:00 → 0:45 (45s)                    [✗ Reject] [← Prev] [Next →]│
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                               │
│  ┌────────────────────────────────────┐  ┌─────────────────────────────────┐ │
│  │  CONFIG PANELS  (left, ~58%)       │  │  PREVIEW + INFO  (right, ~42%)  │ │
│  │                                    │  │                                 │ │
│  │  [Layout] [Style] [Overlays][Gates]│  │  9:16 PREVIEW                   │ │
│  │  ──────────────────────────────── │  │  ┌───────────────────────────┐  │ │
│  │                                    │  │  │                           │  │ │
│  │  (tab content — see 6a/6b/6c/6d)  │  │  │   CLIP FRAME / IMAGE      │  │ │
│  │                                    │  │  │   (preview_url or         │  │ │
│  │                                    │  │  │    generated image)       │  │ │
│  │                                    │  │  │                           │  │ │
│  │                                    │  │  │   Drag handles to adjust  │  │ │
│  │                                    │  │  │   crop (layout tab)       │  │ │
│  │                                    │  │  └───────────────────────────┘  │ │
│  │                                    │  │                                 │ │
│  │                                    │  │  [⟳ Generate Preview]          │ │
│  │                                    │  │  (polls /preview-status/ every 3s│ │
│  │                                    │  │   until ready: true)           │ │
│  │                                    │  │                                 │ │
│  │                                    │  │  ─────────────────────────────  │ │
│  │                                    │  │  CANDIDATE DETAILS              │ │
│  │                                    │  │                                 │ │
│  │                                    │  │  Title                          │ │
│  │                                    │  │  ┌─────────────────────────┐   │ │
│  │                                    │  │  │ The biggest mistake...  │   │ │
│  │                                    │  │  └─────────────────────────┘   │ │
│  │                                    │  │                                 │ │
│  │                                    │  │  Hook Text                      │ │
│  │                                    │  │  ┌─────────────────────────┐   │ │
│  │                                    │  │  │ You won't believe what  │   │ │
│  │                                    │  │  │ happens next...         │   │ │
│  │                                    │  │  └─────────────────────────┘   │ │
│  │                                    │  │  (auto-saves on blur)           │ │
│  │                                    │  │                                 │ │
│  │                                    │  │  Time: 0:00 → 0:45 (45s)        │ │
│  │                                    │  │  Relevance: ★★★★☆ 0.87          │ │
│  │                                    │  │  Excerpt:                       │ │
│  │                                    │  │  "The biggest mistake I see..." │ │
│  └────────────────────────────────────┘  └─────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 6a. Layout Tab

**API:** `GET/PATCH /api/v1/clipping/layout-configs/{id}/`
**Reset:** `POST /api/v1/clipping/layout-configs/{id}/reset-crop/`

```
│  [● Layout] [Style] [Overlays] [Gates]                                       │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                               │
│  Render Mode                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐   │    │
│  │  │  ● Smart Crop    │  │  ○ Center Crop   │  │ ○ Spatial Stack  │   │    │
│  │  │  ──────────────  │  │  ──────────────  │  │  ──────────────  │   │    │
│  │  │  AI speaker      │  │  Static 9:16     │  │  Two-region      │   │    │
│  │  │  tracking crop   │  │  center box      │  │  stacked layout  │   │    │
│  │  └──────────────────┘  └──────────────────┘  └──────────────────┘   │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  Crop Coordinates  (Smart Crop selected)                                      │
│  ──────────────────────                                                       │
│  ○ Auto-detect  (AI face tracking, recommended)                               │
│  ● Manual                                                                     │
│                                                                               │
│  ┌───────────────────────────────┐                                            │
│  │  X offset  [────────●──]  0.10│   Drag the green rectangle in the         │
│  │  Y offset  [●────────── ]  0.00│   preview panel to set crop region.       │
│  │  Width     [──────●────]  0.80│                                            │
│  │  Height    [─────────●─]  1.00│                                            │
│  └───────────────────────────────┘                                            │
│                                                [Reset to Auto-detect]         │
│                                                                               │
│  Output Format                                                                │
│  ○ Vertical 9:16 (selected)   ○ Landscape 16:9   ○ Square 1:1               │
│                                                                               │
│  Face Detection (read-only, from last render)                                 │
│  Face detected: Yes  ·  Confidence: 94%                                       │
```

**Spatial Stack variant (when Spatial Stack selected):**
```
│  Region A  (top panel — e.g. speaker)                                         │
│  ┌──────────────────────┐                                                      │
│  │  X  [────────────●] 0.0  Y  [●────────────] 0.0                          │
│  │  W  [─────────────●] 1.0  H  [──────────●──] 0.5                          │
│  └──────────────────────┘                                                      │
│                                                                               │
│  Region B  (bottom panel — e.g. gameplay / slides)                            │
│  ┌──────────────────────┐                                                      │
│  │  X  [────────────●] 0.0  Y  [──────────●──] 0.5                          │
│  │  W  [─────────────●] 1.0  H  [──────────●──] 0.5                          │
│  └──────────────────────┘                                                      │
│                                                                               │
│  Stack ratio A:B  [────────●───────]  0.60  (A gets 60% of height)           │
```

### 6b. Style Tab

**API:** `PATCH /api/v1/clipping/style-configs/{id}/`
**Template apply:** `POST /api/v1/clipping/style-configs/{id}/apply-template/`

```
│  [Layout] [● Style] [Overlays] [Gates]                                       │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                               │
│  Apply Template                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │  [TikTok Default ▾]                             [Apply Template]   │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│  Applying a template overwrites all style fields below.                      │
│                                                                               │
│  ────────────────────────────────────────────────────────────────────────    │
│                                                                               │
│  ▼ CAPTIONS                                                      [collapse]  │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │  Enabled        [● ON ────────────────────────────────────── OFF]  │     │
│  │                                                                     │     │
│  │  Style          [Word by Word ▾]  WORD | CHUNKED | KARAOKE | FULL  │     │
│  │  Position       [Bottom ▾]        TOP | CENTER | BOTTOM            │     │
│  │  Animation      [Pop ▾]           NONE | POP | SLIDE | FADE        │     │
│  │  Size           [───────────●────────────────]  32px               │     │
│  │  Color          [████ #FFFFFF ▾]                                   │     │
│  │  Stroke color   [████ #000000 ▾]   Stroke width  [──●──]  2px      │     │
│  │  Font           [Inter ▾]                                          │     │
│  │  Translate to   [No translation ▾]  (language dropdown)            │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                               │
│  ▶ HOOK                                                          [expand]    │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │  Enabled  [● ON]    Duration  [──●──────────]  3.0s                │     │
│  │  Style    [Title Card ▾]      Font  [Inter ▾]                      │     │
│  │  Size  [────●──]  28px        Color [████ #FFFFFF]                 │     │
│  │  BG color [████ #000000]      Animation [Slide ▾]                  │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                               │
│  ▶ WATERMARK                                                     [expand]    │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │  Enabled  [● ON]   Type  ● Text  ○ Image                           │     │
│  │  Text     [@mybrand                        ]                        │     │
│  │  Position [Top Right ▾]   Opacity [──────●]  80%   Size [──●──]    │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                               │
│  ▶ PROGRESS BAR                                                  [expand]    │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │  Enabled  [○ OFF]   Position [Bottom ▾]   Color [████ #5B5BD6]     │     │
│  │  Height   [──●──]  4px                                              │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                               │
│  ▶ INTRO / OUTRO                                                 [expand]    │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │  Intro    [● ON]   Asset: [My Intro v2 ▾]   Transition [Fade ▾]   │     │
│  │  Outro    [● ON]   Asset: [Subscribe CTA ▾]  Transition [Slide ▾]  │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                               │
│  ▶ MUSIC                                                         [expand]    │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │  Enabled  [● ON]   Track: [Lo-fi Chill Beat ▾]                     │     │
│  │  Volume   [──────────────────●]  -18 dB                            │     │
│  │  Fade in  [────●─────]  1.0s    Fade out  [──────●───]  2.0s       │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                               │
│  All changes auto-save (PATCH on blur/change with 200ms debounce)           │
│  Subtle "Saved ✓" toast after each save                                      │
```

### 6c. Overlays Tab

**API:** `GET /api/v1/clipping/overlays/?candidate={id}` · `POST` · `PATCH` · `DELETE`

```
│  [Layout] [Style] [● Overlays] [Gates]                                       │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                               │
│  Timed Overlays                                          [+ Add Overlay]     │
│  ──────────────────                                                           │
│  ⓘ Timestamps use final output time (includes intro + hook duration)         │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  #1  "Subscribe for more!"                             [✏] [🗑]      │    │
│  │       5.0s → 8.0s  ·  Pos (0.50, 0.85)  ·  32px  #FFFFFF  90%      │    │
│  ├──────────────────────────────────────────────────────────────────────┤    │
│  │  #2  "Link in bio 👇"                                   [✏] [🗑]      │    │
│  │       12.0s → 15.5s  ·  Pos (0.50, 0.90)  ·  28px  #FFFF00  80%    │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  ── ADD / EDIT OVERLAY FORM (inline, slides open) ──────────────────────    │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Text                                                                │    │
│  │  ┌──────────────────────────────────────────────────────────────┐   │    │
│  │  │ Subscribe for more!                                          │   │    │
│  │  └──────────────────────────────────────────────────────────────┘   │    │
│  │                                                                      │    │
│  │  Start time  [5.0 ]s        End time  [8.0 ]s                        │    │
│  │                                                                      │    │
│  │  Position X  [────────●──────────]  0.50  (0 = left,  1 = right)   │    │
│  │  Position Y  [────────────────●──]  0.85  (0 = top,   1 = bottom)  │    │
│  │                                                                      │    │
│  │  Font size  [32]   Color [████ #FFFFFF]   Opacity [────────●]  90%  │    │
│  │                                                                      │    │
│  │                                      [Cancel]  [Save Overlay]       │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  EMPTY STATE:                                                                │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  No overlays yet.                                                    │    │
│  │  Add timed text or image overlays that appear at specific            │    │
│  │  timestamps in the final clip.                          [+ Add One] │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
```

### 6d. Gates Tab

**API:** `PATCH /api/v1/clipping/candidates/{id}/` → `{ render_gates: [5, 8] }`

```
│  [Layout] [Style] [Overlays] [● Gates]                                       │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                               │
│  Review Gates                                                                 │
│  ─────────────────────────────────────────────────────────────────────────   │
│  Gates pause the render pipeline at specific stages so you can inspect       │
│  the intermediate output before continuing.                                   │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  ☐  Stage 1  — Trim & Crop        Initial crop before any processing │    │
│  │  ☐  Stage 2  — Intro Concat       After intro asset is prepended     │    │
│  │  ☐  Stage 3  — Hook               After hook overlay is rendered     │    │
│  │  ☐  Stage 4  — Caption Translate  After language translation         │    │
│  │  ☑  Stage 5  — Captions           After subtitle burn-in ← active    │    │
│  │  ☐  Stage 6  — Watermark          After watermark is applied         │    │
│  │  ☐  Stage 7  — Timed Overlays     After all timed overlays rendered  │    │
│  │  ☑  Stage 8  — Progress Bar       Before final audio mix ← active    │    │
│  │  ☐  Stage 9  — Outro Concat       After outro asset is appended      │    │
│  │  ☐  Stage 10 — Music Mix          Final mixed output                 │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  Active gates: [5]  [8]                        [Save Gates]  ✓ Saved        │
│                                                                               │
│  ⓘ Tip: Gate 5 (Captions) is the most common review point.                  │
```

---

## 7. Render Detail Page

**Route:** `/clipping/jobs/[jobId]/renders/[renderId]`
**API:** `GET /api/v1/clipping/renders/{id}/`

### 7a. RUNNING — Active render

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ← Back to Job                                                [⋮]            │
│  Render #1 · "The biggest mistake creators make"                              │
│  ⟳ RUNNING                                                                   │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                               │
│  ┌────────────────────────────────────┐  ┌──────────────────────────────┐    │
│  │  STAGE PIPELINE                    │  │  STAGE DETAIL                │    │
│  │  ──────────────────────────────    │  │  ──────────────────────────  │    │
│  │                                    │  │                              │    │
│  │  ┌────────────────────────────┐   │  │  Stage 1 — Trim & Crop       │    │
│  │  │  1  Trim & Crop   ✓  12.4s│   │  │  Status: ✓ COMPLETED         │    │
│  │  ├────────────────────────────┤   │  │  Duration: 12.4s             │    │
│  │  │  2  Intro Concat  —  SKIP │   │  │  Output: stage_1_trim.mp4    │    │
│  │  ├────────────────────────────┤   │  │                              │    │
│  │  │  3  Hook          ✓   3.1s│   │  │  [▶ Preview Stage Output]   │    │
│  │  ├────────────────────────────┤   │  │                              │    │
│  │  │  4  Caption Trans —  SKIP │   │  │  ─────────────────────────── │    │
│  │  ├────────────────────────────┤   │  │                              │    │
│  │  │  5  Captions      ⟳  ...  │   │  │  ← Click any completed stage │    │
│  │  │     ▓▓▓▓▓▓▓▓▓▓░░░ 60%    │   │  │  to preview its output here  │    │
│  │  ├────────────────────────────┤   │  │                              │    │
│  │  │  6  Watermark     ○  wait │   │  │                              │    │
│  │  ├────────────────────────────┤   │  │                              │    │
│  │  │  7  Timed Overlays○  wait │   │  │                              │    │
│  │  ├────────────────────────────┤   │  │                              │    │
│  │  │  8  Progress Bar  ○  wait │   │  │                              │    │
│  │  ├────────────────────────────┤   │  │                              │    │
│  │  │  9  Outro Concat  ○  wait │   │  │                              │    │
│  │  ├────────────────────────────┤   │  │                              │    │
│  │  │ 10  Music Mix     ○  wait │   │  │                              │    │
│  │  └────────────────────────────┘   │  │                              │    │
│  │                                    │  │                              │    │
│  │  ██████████░░░░░░░░  Stage 5/10   │  │                              │    │
│  │  ⟳ Auto-updating via SSE          │  │                              │    │
│  └────────────────────────────────────┘  └──────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 7b. PAUSED_AT_GATE — Gate pause review

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Render #1 · "The biggest mistake creators make"                              │
│  ⏸ PAUSED AT GATE — Stage 5 (Captions)                                      │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                               │
│  ┌────────────────────────────────────┐  ┌──────────────────────────────┐    │
│  │  STAGE PIPELINE                    │  │  STAGE 5 — Captions          │    │
│  │                                    │  │  ──────────────────────────  │    │
│  │  1  Trim & Crop   ✓  12.4s        │  │  Status: ✓ COMPLETED         │    │
│  │  2  Intro Concat  —  SKIP         │  │  Duration: 8.2s              │    │
│  │  3  Hook          ✓   3.1s        │  │                              │    │
│  │  4  Caption Trans —  SKIP         │  │  Output:                     │    │
│  │  5  Captions      ✓   8.2s  ⏸     │  │  stage_5_captions.mp4        │    │
│  │     GATE PAUSED HERE              │  │                              │    │
│  │  6  Watermark     ○  waiting      │  │  [▶ Preview Caption Output] │    │
│  │  7  Timed Overlays○  waiting      │  │                              │    │
│  │  8  Progress Bar  ○  waiting      │  │  ─────────────────────────── │    │
│  │  9  Outro Concat  ○  waiting      │  │  ⚠ Review Required           │    │
│  │  10 Music Mix     ○  waiting      │  │                              │    │
│  │                                    │  │  Check the captions look     │    │
│  │  ──────────────────────────────   │  │  correct before continuing.  │    │
│  │  ┌────────────────────────────┐   │  │                              │    │
│  │  │  ⏸ Paused at Stage 5      │   │  │  If captions need changes:   │    │
│  │  │                            │   │  │  [⚙ Edit Style Config]      │    │
│  │  │  [▶ Resume Pipeline]       │   │  │  then rerun from stage 5.   │    │
│  │  │  [↩ Rerun from Stage 5]   │   │  │                              │    │
│  │  │  [↩ Rerun from Stage 1]   │   │  │  If they look good:          │    │
│  │  └────────────────────────────┘   │  │  [▶ Resume Pipeline →]     │    │
│  └────────────────────────────────────┘  └──────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 7c. COMPLETED — Final output

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Render #1 · "The biggest mistake creators make"                              │
│  ✓ COMPLETED · 47.3s total                                                   │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                               │
│  ┌────────────────────────────────────┐  ┌──────────────────────────────┐    │
│  │  ALL STAGES COMPLETE               │  │  FINAL OUTPUT                │    │
│  │                                    │  │  ──────────────────────────  │    │
│  │  1  Trim & Crop   ✓  12.4s        │  │  ┌────────────────────────┐  │    │
│  │  2  Intro Concat  ✓   2.1s        │  │  │                        │  │    │
│  │  3  Hook          ✓   3.1s        │  │  │  [VIDEO PLAYER 9:16]   │  │    │
│  │  4  Caption Trans —  SKIP         │  │  │  (pre-signed URL)      │  │    │
│  │  5  Captions      ✓   8.2s        │  │  │                        │  │    │
│  │  6  Watermark     ✓   1.8s        │  │  └────────────────────────┘  │    │
│  │  7  Timed Overlays✓   2.3s        │  │                              │    │
│  │  8  Progress Bar  ✓   1.1s        │  │  Duration: 0:51              │    │
│  │  9  Outro Concat  ✓   3.4s        │  │  File size: 8.4 MB           │    │
│  │  10 Music Mix     ✓  10.8s        │  │  Format: Vertical 9:16       │    │
│  │                                    │  │                              │    │
│  │  Total: 47.3s                      │  │  [↓ Download Video]         │    │
│  │                                    │  │                              │    │
│  │  [↩ Rerun from Stage 1]           │  │                              │    │
│  │  [↩ Rerun from Stage N]           │  │                              │    │
│  └────────────────────────────────────┘  └──────────────────────────────┘    │
│                                                                               │
│  DISTRIBUTION                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  ✓ TikTok          POSTED     [↗ View Post]        [⟳ Sync]        │    │
│  │  ⟳ Instagram       POSTING... Uploading...                           │    │
│  │  ○ YouTube Shorts  PENDING                                           │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 7d. FAILED — Error state

```
│  Render #1 · "The biggest mistake creators make"                              │
│  ✗ FAILED at Stage 5 (Captions)                                              │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Stage 1-4: ✓ ✓ — —   Stage 5: ✗ FAILED                           │    │
│  │  ──────────────────────────────────────────────────────────────────  │    │
│  │  Error:                                                              │    │
│  │  ┌──────────────────────────────────────────────────────────────┐   │    │
│  │  │ AssertionError: libass font 'Inter' not found                │   │    │
│  │  │ at stage captions · 2026-05-09 14:44:12 UTC                  │   │    │
│  │  └──────────────────────────────────────────────────────────────┘   │    │
│  │                                                                      │    │
│  │  [↩ Rerun from Stage 5]          [↩ Rerun from Stage 1]            │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
```

---

## 8. Job Detail — Rendering View (all candidates)

When job reaches `RENDERING`, the job detail page shows per-candidate render cards.
**Route:** `/clipping/jobs/[jobId]` (same URL as Phase A/B)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ← Jobs                                                          [⋮]         │
│  How to grow on YouTube in 2025                                               │
│  ⟳ RENDERING · 5 clips · 1 completed                                        │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                               │
│  RENDER PROGRESS                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  ┌────────────────────────────────────────────────────────────────┐ │    │
│  │  │  "The biggest mistake creators make"      ⟳ Stage 5/10        │ │    │
│  │  │  0:00 → 0:45  ████████████░░░░░░░░  50%    [View Render →]   │ │    │
│  │  ├────────────────────────────────────────────────────────────────┤ │    │
│  │  │  "3 things YouTube never tells you"       ⟳ Stage 3/10        │ │    │
│  │  │  1:32 → 2:10  ████░░░░░░░░░░░░░░░░  30%    [View Render →]   │ │    │
│  │  ├────────────────────────────────────────────────────────────────┤ │    │
│  │  │  "Going viral in 2025"                    ✓ COMPLETED          │ │    │
│  │  │  3:15 → 4:02  ████████████████████  100%   [↓ DL] [View →]   │ │    │
│  │  ├────────────────────────────────────────────────────────────────┤ │    │
│  │  │  "The #1 retention tip"                   ⏸ PAUSED at Gate 5  │ │    │
│  │  │  5:00 → 5:52  ██████████░░░░░░░░░░         [Review Gate →]    │ │    │
│  │  ├────────────────────────────────────────────────────────────────┤ │    │
│  │  │  "Why 90% of creators quit"               ✗ FAILED (Stage 5)  │ │    │
│  │  │  7:22 → 8:11                              [View Error →]       │ │    │
│  │  └────────────────────────────────────────────────────────────────┘ │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  ⟳ Auto-refreshing every 3s                                                  │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Distribution & Analytics

Accessible from the completed Render Detail page as a dedicated tab.
**API:** `GET /api/v1/clipping/posts/?render={id}` · `POST /api/v1/clipping/posts/{id}/sync-analytics/`

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Render #1 · "The biggest mistake creators make"  ✓ COMPLETED               │
│  [Pipeline] [● Distribution & Analytics]                                     │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                               │
│  DISTRIBUTION STATUS                                      [⟳ Sync All]      │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  TikTok                                         ✓ POSTED             │    │
│  │  Posted: 2026-05-09 15:00 UTC     [↗ View on TikTok]  [⟳ Sync]     │    │
│  │  ──────────────────────────────────────────────────────────────────  │    │
│  │  ┌──────────┬──────────┬──────────┬──────────┬────────────────────┐ │    │
│  │  │ 👁 Views  │ ❤ Likes  │ 💬 Cmnts │ ↗ Shares │ 💰 Revenue         │ │    │
│  │  │  12,405  │   843    │   57     │   234    │ $1.24 USD          │ │    │
│  │  └──────────┴──────────┴──────────┴──────────┴────────────────────┘ │    │
│  │  Last synced: 5 min ago                                              │    │
│  ├──────────────────────────────────────────────────────────────────────┤    │
│  │  Instagram Reels                                ⟳ POSTING...        │    │
│  │  Uploading to Instagram...                                           │    │
│  ├──────────────────────────────────────────────────────────────────────┤    │
│  │  YouTube Shorts                                 ✗ FAILED             │    │
│  │  Error: OAuth token expired. Auto-retry in: 1m 45s                  │    │
│  │  ⓘ Fix OAuth in Settings to allow retry.                            │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 10. Asset Library

### 10a. Media Assets (Intro / Outro)

**Route:** `/library/media-assets`
**API:** `GET /api/v1/clipping/media-assets/?asset_type=INTRO|OUTRO`

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Media Assets                                          [+ Upload Asset]      │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                               │
│  [All ▾]  [Intro ▾]  [Outro ▾]                                              │
│                                                                               │
│  INTRO                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  ┌─────────────┐  My Intro v2              INTRO  ✓ Active           │    │
│  │  │ [THUMBNAIL] │  intro_v2.mp4  ·  4.2s  ·  12.4 MB      [▶] [⋮]   │    │
│  │  └─────────────┘                                                      │    │
│  ├──────────────────────────────────────────────────────────────────────┤    │
│  │  ┌─────────────┐  My Intro v1              INTRO  ○ Inactive         │    │
│  │  │ [THUMBNAIL] │  intro_v1.mp4  ·  3.8s  ·  10.1 MB      [▶] [⋮]   │    │
│  │  └─────────────┘                                                      │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  OUTRO                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  ┌─────────────┐  Subscribe CTA            OUTRO  ✓ Active           │    │
│  │  │ [THUMBNAIL] │  outro_cta.mp4  ·  5.0s  ·  15.3 MB     [▶] [⋮]   │    │
│  │  └─────────────┘                                                      │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
```

**⋮ menu:** Rename · Set active/inactive · Delete (with confirm)
**Upload dialog:** same dropzone pattern as Create Job upload

### 10b. Music Assets

**Route:** `/library/music`
**API:** `GET /api/v1/clipping/music-assets/`

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Music Assets                                          [+ Upload Track]      │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Lo-fi Chill Beat               ✓ Active                    [⋮]      │    │
│  │  ⏵  ▁▂▃▄▃▂▁▂▄▅▄▃▁▂▃▄▃▂▁▂▄▅▃▂▁  ─────●──────────────────  3:24    │    │
│  │  3:24  ·  4.2 MB  ·  85 BPM  ·  Lo-fi                               │    │
│  ├──────────────────────────────────────────────────────────────────────┤    │
│  │  Upbeat Energizer               ✓ Active                    [⋮]      │    │
│  │  ⏵  ▁▄▇▅▃▅▇▅▃▁▄▇▅▃▅▇▅▃▁▄▇▅▃▁  ●────────────────────────  2:45    │    │
│  │  2:45  ·  3.8 MB  ·  128 BPM  ·  Pop                                │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Waveform** shown inline (from `waveform_file`). Click ⏵ to play preview.

### 10c. Render Templates

**Route:** `/library/templates`
**API:** `GET /api/v1/clipping/render-templates/`

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Render Templates                                       [+ New Template]     │
│  ──────────────────────────────────────────────────────────────────────────  │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  TikTok Default                                           ★ DEFAULT  │    │
│  │  ─────────────────────────────────────────────────────────────────── │    │
│  │  Captions: Word by Word · Bottom · Pop · Inter · 32px                │    │
│  │  Watermark: @mybrand · Top Right · 80% opacity                       │    │
│  │  Music: Lo-fi Chill Beat · -18 dB · 1s/2s fade                      │    │
│  │  Hook: 3s Title Card                                                  │    │
│  │                                                     [Edit] [⋮]       │    │
│  ├──────────────────────────────────────────────────────────────────────┤    │
│  │  Instagram Reels                                                      │    │
│  │  ─────────────────────────────────────────────────────────────────── │    │
│  │  Captions: Chunked · Center · Fade                                   │    │
│  │  Progress bar: Bottom · 4px                                          │    │
│  │                            [Set as Default]  [Edit]  [🗑 Delete]    │    │
│  │  ⓘ Cannot delete the default template.                               │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Edit template** opens a full-page style editor identical to Style Tab (§6b) but scoped to the template.

---

## 11. Global UX States

### Loading skeletons (initial page load)

```
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░   (shimmer animation)          │    │
│  │  ▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░                                 │    │
│  │  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░                                  │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
```

Use shadcn `<Skeleton>` for every table row / card while data loads.

### Toast notifications

All mutations show a transient toast (bottom-right, shadcn `<Toaster>`):
- `✓ Candidate approved` (green)
- `✓ Gates saved` (green)
- `✓ Style saved` (green)
- `✗ Failed to save — retrying...` (red)

### Confirm dialogs

Destructive actions (delete job, delete overlay, reject candidate) use a `<Dialog>` with
a red `[Confirm Delete]` CTA and `[Cancel]`.

### Disabled state for Start Rendering

```
│  [▶ Start Rendering]   ← disabled (grey)                                    │
│  Tooltip on hover: "Approve at least one candidate to render"                │
```

---

## 12. Page Route Map

| Route | Description | API Endpoints |
|-------|-------------|---------------|
| `/clipping/jobs` | Job list + create | `GET /jobs/` |
| `/clipping/jobs/[id]` | Job detail (all phases) | `GET /jobs/{id}/` + SSE `stream/` |
| `/clipping/jobs/[id]/candidates/[cId]` | Candidate config | `GET /candidates/{id}/` |
| `/clipping/jobs/[id]/renders/[rId]` | Render detail + gate actions | `GET /renders/{id}/` |
| `/library/media-assets` | Intro/outro library | `GET /media-assets/` |
| `/library/music` | Music library | `GET /music-assets/` |
| `/library/templates` | Render templates | `GET /render-templates/` |

---

## 13. Real-time Strategy

| Mechanism | When used |
|-----------|-----------|
| SSE (`EventSource`) | Primary: job pipeline progress, render stage updates |
| REST polling every 3s | Render detail page (stage updates) |
| REST polling every 5s | SSE fallback when connection drops |
| Debounced PATCH (200ms) | Style config, layout config, title/hook auto-save |
| Optimistic update | Approve / reject candidate — flip card state immediately, revert on error |

SSE events to handle:
- `analysis_complete` → switch job from pipeline-progress view to candidate-review view
- `render_started` → show render card in job detail
- `stage_complete` → update stage pill in render detail
- `render_paused` → show gate-pause state with amber banner
- `render_complete` → show COMPLETED state, enable download
- `post_complete` → update distribution status row

---

## Verification

To validate these mockups during frontend implementation:

1. **API shape check** — run `GET /api/v1/clipping/jobs/` against the running backend and confirm all
   fields referenced in tables/cards exist in the serializer response.
2. **SSE check** — open `GET /api/v1/clipping/jobs/{id}/stream/` in a browser tab or with `curl --no-buffer`
   and confirm event names match the reference in Section 13.
3. **Happy path** — create a job with a YouTube URL, step through each phase and confirm each screen
   in this doc renders correctly with live data.
4. **Gate pause** — set `render_gates: [5]` on a candidate, start render, confirm the PAUSED_AT_GATE
   screen (§7b) appears and that Resume/Rerun buttons call the correct endpoints.
5. **Dark/light toggle** — toggle theme and verify all status badges and color-coded elements remain
   legible in both modes.
