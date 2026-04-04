# ReelForge Dashboard — Frontend Architecture Design

**Date:** 2026-04-04  
**Scope:** Phase 1 — Clipping pipeline UI. YouTube pipeline follows same patterns.  
**Audience:** Internal operators (29signals team). Not client-facing yet.

---

## 1. Problem

Django admin (Unfold) is the current operator interface. It is adequate for raw data access but insufficient for:

- **Pipeline visibility** — no way to watch stages progress in real time without refreshing
- **Approval workflows** — the `AWAITING_CLIP_APPROVAL` gate exists in the FSM but has no usable review UI; operators cannot preview, edit, or selectively approve clip candidates
- **Render oversight** — 10-stage render pipeline runs as a black box; no per-stage preview, no way to pause and adjust config mid-run
- **Visual configuration** — `ClipLayoutConfig` region coordinates (Smart Crop override, Spatial Stack regions A/B) must be typed as raw integers in admin with no visual feedback

Django admin is **kept** as a power-user / debug surface. The new dashboard is a purpose-built second surface for workflow operations.

---

## 2. Decision

Build a dedicated dashboard app using:

- **Django template engine** — server-rendered HTML, no SPA
- **HTMX** — live partial updates, form submissions without full page reloads, polling
- **Alpine.js** — client-side state (toggles, tab switching, drag interactions for region editor)
- **Tailwind CSS** — utility-first styling with a build step (`tailwindcss` CLI via `uv`)
- **No WebSockets / Django Channels** — HTMX polling at 2s intervals is sufficient for Celery job status

Dark theme throughout. Dense, power-user layout. Visual polish is secondary to functionality for now.

---

## 3. Architecture

### 3.1 App Structure

**Option chosen: Thin `ui` app for layout + views stay in domain apps.**

```
***REMOVED***/
  ui/                         ← new Django app
    apps.py
    urls.py                   ← mount point at /app/ — includes all domain view URLs
    views.py                  ← dashboard home view only (cross-domain)
    templates/
      ui/
        base.html             ← top nav + left sidebar shell
        partials/
          job_row.html        ← reusable active job row with HTMX status polling
          stage_pill.html     ← reusable render stage pill
          status_badge.html   ← color-coded FSM status badge

  clipping/
    views.py                  ← all clipping UI views (added to existing app)
    urls.py                   ← /app/clipping/...
    templates/
      clipping/
        job_list.html
        job_detail.html
        clip_candidate_detail.html
        render_detail.html
        partials/
          job_status.html     ← polled partial: current status + stage
          stage_list.html     ← polled partial: render stage progress
          clip_candidate_row.html

  channels/
    views.py                  ← channel list, channel detail, render template config
    urls.py                   ← /app/channels/...
    templates/
      channels/
        ...
```

The `ui` app owns the base template and shared partials only. Domain logic and views stay with their domain app. Adding a new domain (YouTube) means adding `views.py` + `urls.py` to that app and registering it in `ui/urls.py`.

### 3.2 URL Layout

```
/app/                         → dashboard home
/app/clipping/                → clipping job list
/app/clipping/<job_id>/       → clipping job detail + clip candidates
/app/clipping/clips/<id>/     → clip candidate detail (config + render CTA)
/app/clipping/renders/<id>/   → render detail (stage progress + preview + gates)

/app/channels/                → channel list
/app/channels/<id>/           → channel detail + render template config

/app/youtube/                 → YouTube pipeline (Phase 2)
```

All views require `login_required`. Staff-only for now (`@staff_member_required`).

### 3.3 Base Layout

```
┌─────────────────────────────────────────────────────────────┐
│  [RF]  ReelForge   Dashboard  Clipping  YouTube  Channels   │  ← top nav
├───────────────┬─────────────────────────────────────────────┤
│  Overview     │                                             │
│  Active Jobs  │                                             │
│               │          Main content area                  │
│  Clipping     │                                             │
│  All Jobs     │                                             │
│  ⚠ Approval 3 │                                             │
│  Completed    │                                             │
│               │                                             │
│  YouTube      │                                             │
│  Pipelines    │                                             │
│  Scripts      │                                             │
│               │                                             │
│  ─────────── │                                             │
│  Settings     │                                             │
└───────────────┴─────────────────────────────────────────────┘
```

- Top nav: branding, section tabs (Dashboard / Clipping / YouTube / Channels), "+ New Job" CTA, user avatar
- Left sidebar: 192px wide, context-sensitive sub-navigation per section
- Active section tab highlighted in indigo; active sidebar item in `bg-slate-700`
- Amber badge on "Awaiting Approval" sidebar item showing pending count

---

## 4. Pages — Phase 1 (Clipping)

### 4.1 Dashboard Home (`/app/`)

**Stats row:** Active Jobs / Awaiting Approval / Completed Today / Channels Active — each a card with a large number and color accent.

**Active Jobs panel (2/3 width):** Live list of all in-progress jobs across both pipelines. Each row shows: status dot (color-coded, pulsing if active), job title, pipeline type, current stage label, progress bar (where applicable), time elapsed. Rows are clickable → job detail. HTMX polls the entire panel every 2s; the partial replaces only the rows, not the card header.

**Needs Attention panel (1/3 width):** Jobs stuck at `AWAITING_CLIP_APPROVAL`. Each row is a direct link to the clip approval view with a count badge.

**Completed Today panel:** Recent completions with timestamp.

### 4.2 Clipping Job List (`/app/clipping/`)

Filterable by status (All / Active / Awaiting Approval / Completed / Failed). Table view: job title, source type, channel, status badge, clip count, created time, actions. Status badges poll via HTMX for active jobs.

### 4.3 Clipping Job Detail (`/app/clipping/<job_id>/`)

**Pipeline stage tracker:** Horizontal strip showing the 8 main `ClippingJob` FSM states (Init → Download → Transcribe → Analyze → Approval → Render → Distribute → Done). Completed = green checkmark, current = amber/indigo pulse, pending = grey. Polled every 2s while job is active.

**Clip candidates section** (shown when status is `AWAITING_CLIP_APPROVAL` or later):

Each clip candidate card shows:
- Video thumbnail with play button (links to source video at `#t=start_sec,end_sec`)
- Inline-editable title (HTMX PATCH on blur)
- Inline-editable start/end timestamps (HTMX PATCH on blur, duration auto-calculated)
- AI virality score + hook type label
- Status: pending (Approve / Reject buttons) / approved (green badge + X to un-approve) / rejected (faded with undo)

Bottom bar: count of approved/pending/rejected clips + estimated render time + "Start Rendering N Clips" CTA.

"Approve All" bulk action applies to all pending candidates.

### 4.4 Clip Candidate Detail (`/app/clipping/clips/<candidate_id>/`)

Split layout: visual editor (left) + config panels (right).

**Render Mode Selector:** Three mode cards (Smart Crop / Spatial Stack / Center Crop) with visual icons. Clicking a mode saves via HTMX PATCH and swaps the visual editor panel below.

**Output Format:** Dropdown (Vertical 9:16 / Square 1:1 / Landscape 16:9).

**Visual Layout Editor:**

For **Smart Crop**:
- Source frame (16:9 `<div>` with proportional dimensions) rendered with Alpine.js drag + resize overlay
- An indigo-bordered region box is absolutely positioned; Alpine tracks `x/y/w/h` state and writes to hidden inputs
- Face detection dot shown if `face_detected=True` and `detection_confidence` is present
- `manual_crop_x/y/w/h` coordinate fields shown below frame for manual entry
- "Reset to auto" clears all four manual fields via HTMX DELETE

For **Spatial Stack**:
- Same source frame with two independently draggable region boxes: Region A (indigo) and Region B (cyan)
- Each box maps to `region_a_x/y/w/h` and `region_b_x/y/w/h` on `ClipLayoutConfig`
- Stack ratio slider (0.3–0.8) controlling how much vertical space Region A takes in the output
- Output preview shows the stacked result with the ratio applied

For **Center Crop**:
- No interactive regions — just a static center-crop indicator overlay
- Output preview shown

**9:16 Output Preview:**
- Shows the `preview_image` from `ClipLayoutConfig` if set
- "Generate Preview" button fires `preview_clip_layout` Celery task via HTMX POST
- After POST, preview area polls `/app/clipping/clips/<id>/preview_status/` every 2s until `preview_image` is populated, then swaps the image in

**Right config panels** (all collapsible via Alpine toggle):
- **Captions:** enabled toggle, style, position, animation, font size, color, stroke color
- **Hook:** enabled toggle, style, duration, animation
- **Transitions:** intro + outro dropdowns
- **Watermark:** enabled toggle, type, text/image, position, opacity, size
- **Background Music:** enabled toggle, music asset picker, volume dB, fade in/out
- **Timed Overlays:** list of `ClipTimedOverlay` records; add/remove/edit inline; each has text, start_sec, end_sec, position_x/y
- **Channel defaults note:** reminder that these are per-clip overrides; "Reset to channel defaults" link

All config changes save via HTMX PATCH partials on blur/change. No explicit save button needed.

### 4.5 Render Detail (`/app/clipping/renders/<render_id>/`)

**Stage list (left):** All 10 `ClipRenderStageResult` records displayed as pills. States:
- `COMPLETED` — green checkmark, duration, "▶ preview" button (opens preview panel on the right), "↺ Re-run from stage N" button
- `RUNNING` — indigo pulse, progress bar (where available)
- `PAUSED_AT_GATE` — amber pulse, "✓ Continue" + "Edit config ↺" buttons
- `SKIPPED` — grey, skipped reason label
- `FAILED` — red, error message expandable, "↺ Retry" button
- `PENDING` — grey, dimmed

Polled every 2s while render is active. Polling stops when `ClipRender` reaches a terminal state or gate pause.

**Preview panel (right):** Shows the `output_file` video for whichever stage is selected (clicked from left panel or auto-shown at gate). Native `<video>` element with controls. Stage-specific config quick-edit fields below the preview for immediate adjustment before re-running.

**Re-run mechanics:**
- "Re-run from stage N" → POST to `rerun_from_stage` view → calls `render_clip.delay(render_id, start_from_stage=N)` — deletes stage results for stages ≥ N and re-runs
- "Continue pipeline" at gate → POST to `resume_render` view → calls `render_clip.delay(render_id, start_from_stage=gate_stage+1)`

**Review gates panel (right, below preview):** Toggle switches for 4 natural gate points:
1. After Stage 1 (Trim + Crop) — preview raw crop
2. After Stage 3 (Hook) — verify hook text + animation
3. After Stage 5 (Captions) — verify caption style + readability
4. After Stage 8 (Overlays + Watermark) — final branding check before encode

Gate settings are stored as a `render_gates` JSONField on `ClipCandidate` (e.g. `{"gates": [5, 8]}`). Channel-level defaults stored as a matching JSONField on `Channel` or `ClipRenderTemplate`. A per-clip value of `null` means "use channel default".

**Model changes required:**
- `ClipCandidate`: add `render_gates = JSONField(default=None, blank=True, null=True)`
- `ClipRender.Status`: add `PAUSED_AT_GATE = "PAUSED_AT_GATE"` to the `Status` choices (new FSM state)
- `ClipRender`: add `paused_at_stage = PositiveIntegerField(null=True, blank=True)` to record which stage triggered the pause

When a gate is active, the render task checks after the gate stage completes: if that stage number is in `render_gates`, it sets `ClipRender.status = PAUSED_AT_GATE` and saves `paused_at_stage` instead of continuing. The UI polls this status and swaps in the review panel automatically.

---

## 5. HTMX Polling Pattern

```html
<!-- Self-stopping poll: stops when data-terminal="true" is set on the element -->
<div id="job-status-{{ job.id }}"
     hx-get="{% url 'clipping:job_status_partial' job.id %}"
     hx-trigger="every 2s [!this.dataset.terminal]"
     hx-swap="outerHTML">
  {% include "clipping/partials/job_status.html" %}
</div>
```

The partial returned by the view sets `data-terminal="true"` when the job reaches a terminal state (COMPLETED / FAILED / PAUSED_AT_GATE). HTMX stops polling automatically — no JavaScript needed.

For the render stage list, the entire `<div id="stage-list">` is polled and swapped. Completed stages render without the poll trigger so they do not re-poll unnecessarily.

---

## 6. Tailwind Build Setup

Tailwind CSS is a Node.js tool. Use the **standalone Tailwind CLI binary** — no Node.js install required, no `package.json`, no npm.

```bash
# Download the standalone binary (macOS arm64 example)
curl -sLO https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-macos-arm64
chmod +x tailwindcss-macos-arm64
mv tailwindcss-macos-arm64 bin/tailwindcss   # commit to repo, gitignore the binary per-platform

# tailwind.config.js at project root
# content: ["./***REMOVED***/**/templates/**/*.html"]

# Commands (added to justfile)
just tailwind-watch   → ./bin/tailwindcss -i ./***REMOVED***/ui/static/css/input.css -o ./***REMOVED***/static/css/tailwind.css --watch
just tailwind-build   → ./bin/tailwindcss -i ... -o ... --minify
```

The compiled `tailwind.css` is committed to `***REMOVED***/static/css/` for development. The Docker build runs `just tailwind-build` during image construction so the minified file is baked in. The binary itself is platform-specific and gitignored; the justfile documents how to download it.

---

## 7. Spatial Stack Region Editor — Alpine.js

```html
<div x-data="regionEditor({ ax: {{ config.region_a_x }}, ay: {{ config.region_a_y }}, ... })"
     @mouseup="saveRegions()"
     class="relative" style="padding-top: 56.25%;">

  <!-- Region A box -->
  <div class="absolute border-2 border-indigo-500 cursor-move"
       :style="regionAStyle"
       @mousedown.stop="startDrag($event, 'a')">
    <div class="resize-handle absolute bottom-0 right-0 w-3 h-3 bg-indigo-500 cursor-se-resize"
         @mousedown.stop="startResize($event, 'a')"></div>
  </div>

  <!-- Region B box -->
  <div class="absolute border-2 border-cyan-500 cursor-move"
       :style="regionBStyle"
       @mousedown.stop="startDrag($event, 'b')">...</div>

  <!-- Hidden inputs — submitted via HTMX -->
  <input type="hidden" name="region_a_x" :value="regions.a.x">
  ...
</div>
```

`saveRegions()` fires an HTMX-triggered form submission to `update_layout_config` on mouseup, saving coordinates to `ClipLayoutConfig` via a PATCH view. Debounced to avoid rapid saves during drag.

---

## 8. What Is Not In Scope (Phase 1)

- YouTube pipeline UI (same patterns, Phase 2)
- Client-facing views (polished presentation, access control per client)
- Mobile responsiveness (internal tool, desktop-only for now)
- Bulk operations beyond "Approve All" on clip candidates
- Notification system (email/Slack alerts when gates pause)

---

## 9. Key Files to Create

| File | Purpose |
|---|---|
| `***REMOVED***/ui/apps.py` | New `ui` app registration |
| `***REMOVED***/ui/urls.py` | Root `/app/` mount + domain URL includes |
| `***REMOVED***/ui/views.py` | Dashboard home view |
| `***REMOVED***/ui/templates/ui/base.html` | Top nav + sidebar shell with Tailwind + HTMX + Alpine |
| `***REMOVED***/ui/templates/ui/partials/` | Shared reusable partials |
| `***REMOVED***/clipping/views.py` | All clipping UI views |
| `***REMOVED***/clipping/urls.py` | Clipping URL patterns |
| `***REMOVED***/clipping/templates/clipping/` | All clipping templates + partials |
| `***REMOVED***/ui/static/css/input.css` | Tailwind CSS entry point |
| `tailwind.config.js` | Tailwind content paths |
| `justfile` (updated) | `tailwind-watch` + `tailwind-build` commands |
| `config/settings/base.py` (updated) | Add `***REMOVED***.ui` to `INSTALLED_APPS`, update `STATICFILES_DIRS` |

---

*ReelForge — Dashboard Frontend Architecture*  
*Stack: Django templates · HTMX · Alpine.js · Tailwind CSS*
