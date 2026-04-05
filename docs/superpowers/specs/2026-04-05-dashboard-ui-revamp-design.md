# Dashboard UI Revamp — Design Spec

**Date:** 2026-04-05  
**Status:** Approved  

---

## Overview

Replace the current hand-rolled dark Tailwind dashboard with the **Modernize** template (`mode-template/`). All pages share a new base shell. All Django views are converted from function-based to class-based. No new functionality is added — this is a visual revamp only.

---

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Template integration | Option A — use `theme.css` as-is | Full visual fidelity; fastest path |
| Theme | Dark | Consistent with current; user preference |
| Sidebar layout | Full 270px vertical sidebar | Familiar operator feel |
| Nav sections | Dashboard, Clipping, YouTube (placeholder), Channels (placeholder) | User-specified |
| Views | Class-based only — no FBVs | Project standard |
| JS stack | Preline UI (sidebar/dropdowns) + HTMX + Alpine.js | Preline handles shell; HTMX handles partials |

---

## Static Assets

Copy from `mode-template/assets/` into `reelforge/static/`:

```
reelforge/static/
  vendor/
    modernize/
      css/
        theme.css          ← copied from mode-template/assets/css/theme.css
      libs/
        simplebar/          ← for scrollable sidebar
```

Copy from `mode-template/assets/libs/` into `reelforge/static/vendor/modernize/libs/`:
- `preline/dist/preline.js`
- `simplebar/dist/simplebar.min.css` + `simplebar.min.js`

CDN additions to `base.html` (no download needed):
- **Tabler Icons**: `https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@2.44.0/tabler-icons.min.css`
- **Plus Jakarta Sans**: Google Fonts

Keep existing:
- HTMX 2.0.4
- Alpine.js 3.14

---

## Base Template (`ui/base.html`)

Replaces the existing `base.html` entirely. Structure follows `mode-template/main/index.html`:

```
<html data-color-theme="Blue_Theme" class="dark selected" data-layout="vertical">
  <head>
    <!-- theme.css, tabler icons CDN, Plus Jakarta Sans, Preline UI -->
    <!-- HTMX, Alpine.js -->
  </head>
  <body class="bg-dark">
    <div id="main-wrapper" class="flex">

      <!-- Sidebar: hs-overlay pattern, 270px, dark -->
      <aside id="application-sidebar-brand" class="left-sidebar ...">
        <!-- Logo -->
        <!-- Nav sections: Home, Clipping, YouTube, Channels -->
        <!-- Each item: sidebar-link dark-sidebar-link + ti-* icon + label -->
        <!-- Active item gets: active activemenu -->
        <!-- Badge on Awaiting Approval count (amber) -->
      </aside>

      <!-- Main wrapper -->
      <div class="w-full page-wrapper">
        <!-- Top header bar with mobile toggle + user avatar -->
        <header class="topbar ...">...</header>

        <!-- Page content -->
        <div class="container-fluid">
          <div class="page-container">
            {% block page_header %}{% endblock %}
            {% block content %}{% endblock %}
          </div>
        </div>
      </div>

    </div>
    {% block extra_js %}{% endblock %}
  </body>
</html>
```

Context variable `nav_active` (e.g. `"dashboard"`, `"clipping"`) drives the `active activemenu` class on sidebar links.

---

## Views

All views converted to CBVs. Staff access via a `StaffRequiredMixin` that wraps `staff_member_required`.

### `reelforge/ui/views.py`

| Class | URL | Notes |
|---|---|---|
| `DashboardView` | `/app/` | Replaces `dashboard` FBV |
| `ActiveJobsPartialView` | `/app/partials/active-jobs/` | HTMX partial, polled every 2s |

### `reelforge/clipping/views/jobs.py`

| Class | URL | Notes |
|---|---|---|
| `JobListView` | `/app/clipping/` | Replaces `job_list` FBV |
| `JobDetailView` | `/app/clipping/<uuid:job_id>/` | Replaces `job_detail` FBV |
| `JobStatusPartialView` | `/app/clipping/<uuid:job_id>/status/` | HTMX partial |

### `reelforge/clipping/views/candidates.py`

| Class | URL | Notes |
|---|---|---|
| `CandidateDetailView` | `/app/clipping/clips/<uuid:candidate_id>/` | Replaces `candidate_detail` FBV |
| `UpdateLayoutConfigView` | `/app/clipping/clips/<uuid:candidate_id>/layout/` | HTMX POST |
| `UpdateLayoutRegionsView` | `/app/clipping/clips/<uuid:candidate_id>/layout/regions/` | HTMX POST |
| `ResetSmartCropView` | `/app/clipping/clips/<uuid:candidate_id>/layout/reset-crop/` | HTMX POST |
| `UpdateStyleConfigView` | `/app/clipping/clips/<uuid:candidate_id>/style/` | HTMX POST |
| `TriggerPreviewView` | `/app/clipping/clips/<uuid:candidate_id>/preview/trigger/` | HTMX POST |
| `PreviewStatusView` | `/app/clipping/clips/<uuid:candidate_id>/preview/status/` | HTMX GET |
| `AddOverlayView` | `/app/clipping/clips/<uuid:candidate_id>/overlays/add/` | HTMX POST |
| `UpdateOverlayView` | `/app/clipping/overlays/<uuid:overlay_id>/update/` | HTMX POST |
| `DeleteOverlayView` | `/app/clipping/overlays/<uuid:overlay_id>/delete/` | HTMX DELETE |
| `CandidateApproveView` | `/app/clipping/clips/<uuid:candidate_id>/approve/` | HTMX POST |
| `CandidateRejectView` | `/app/clipping/clips/<uuid:candidate_id>/reject/` | HTMX POST |
| `CandidateUndoRejectView` | `/app/clipping/clips/<uuid:candidate_id>/undo-reject/` | HTMX POST |
| `UpdateRenderGatesView` | `/app/clipping/clips/<uuid:candidate_id>/gates/` | HTMX POST |
| `JobApproveAllView` | `/app/clipping/<uuid:job_id>/approve-all/` | HTMX POST |
| `JobStartRenderView` | `/app/clipping/<uuid:job_id>/start-render/` | HTMX POST |

### `reelforge/clipping/views/renders.py`

| Class | URL | Notes |
|---|---|---|
| `RenderDetailView` | `/app/clipping/renders/<uuid:render_id>/` | Replaces `render_detail` FBV |
| `StageListPartialView` | `/app/clipping/renders/<uuid:render_id>/stages/` | HTMX partial |
| `RerunFromStageView` | `/app/clipping/renders/<uuid:render_id>/rerun/<int:stage_order>/` | HTMX POST |
| `ResumeRenderView` | `/app/clipping/renders/<uuid:render_id>/resume/` | HTMX POST |

---

## Template Changes

### Key CSS classes from `theme.css` to use

**Cards:**
```html
<div class="card">
  <div class="card-body">
    <h5 class="card-title">Title</h5>
    <p class="card-subtitle">Subtitle</p>
  </div>
</div>
```

**Stats cards (dashboard):**
```html
<div class="card shadow-none bg-lightprimary dark:bg-darkprimary">
  <div class="card-body">
    <p class="text-primary font-semibold">Label</p>
    <h5 class="text-2xl font-semibold text-primary">42</h5>
  </div>
</div>
```

**Tables:**
```html
<div class="border overflow-hidden border-light-dark rounded-md">
  <table class="min-w-full divide-y divide-border dark:divide-darkborder">
    <thead>
      <tr>
        <th class="p-4 text-start text-base font-semibold text-link dark:text-white capitalize">Col</th>
      </tr>
    </thead>
    <tbody class="divide-y divide-border dark:divide-darkborder">
      <tr>
        <td class="p-4 whitespace-nowrap">Value</td>
      </tr>
    </tbody>
  </table>
</div>
```

**Status badges:**
```html
<!-- success -->  <span class="badge-md bg-lightsuccess text-success dark:bg-darksuccess dark:text-success">Completed</span>
<!-- warning -->  <span class="badge-md bg-lightwarning text-warning dark:bg-darkwarning dark:text-warning">Pending</span>
<!-- error -->    <span class="badge-md bg-lighterror text-error dark:bg-darkerror dark:text-error">Failed</span>
<!-- primary -->  <span class="badge-md bg-lightprimary text-primary dark:bg-darkprimary dark:text-primary">Active</span>
<!-- info -->     <span class="badge-md bg-lightinfo text-info dark:bg-darkinfo dark:text-info">Analyzing</span>
```

**Action dropdown (table row action menu):**
```html
<div class="hs-dropdown relative inline-flex">
  <button class="hs-dropdown-toggle h-10 w-10 ..."><i class="ti ti-dots-vertical text-lg"></i></button>
  <div class="hs-dropdown-menu ...">
    <a href="..."><i class="ti ti-eye"></i> View</a>
  </div>
</div>
```

---

## Pages

### Dashboard (`/app/`)

- **Stats row**: 4 cards using `card shadow-none bg-light{color}` — Active Jobs (primary), Awaiting Approval (warning), Completed Today (success), Total Channels (info)
- **Main content**: Two-column layout — active jobs table (left, polled via HTMX every 2s) + needs attention panel (right, amber-bordered card)
- **Active jobs table**: Uses template table classes; columns: Title, Channel, Status badge, Started

### Clipping Job List (`/app/clipping/`)

- **Status filter tabs**: Tab bar using `btn` variants; active tab uses `btn-primary`
- **Table**: Template table classes; columns: Title + source URL subtitle, Channel, Status badge, Clip count, Created date, Action link
- **Row click**: Full row is a link to job detail

### Clipping Job Detail (`/app/clipping/<id>/`)

- **Page header**: Job title + status badge + breadcrumb
- **Stage tracker strip**: HTMX-polled, existing partial reused with new styling
- **Candidate cards**: Grid of cards using `card` class — each card shows title, score, status badge, action buttons

### Candidate Detail (`/app/clipping/clips/<id>/`)

- All existing panels (layout editor, style config, overlays, gates, preview) preserved
- Panels wrapped in `card` + `card-body`; tabs for layout/style/overlays/gates using template tab component

### Render Detail (`/app/clipping/renders/<id>/`)

- Stage list in a `card`; each stage row uses template table styling
- Action buttons (rerun, resume) use `btn btn-primary` / `btn btn-outline-primary`

---

## Sidebar Nav Detail

```
[RF logo]

── HOME ──
  Dashboard          ti-home
  
── CLIPPING ──
  All Jobs           ti-scissors   [badge: awaiting count if > 0]
  
── YOUTUBE ──
  Pipeline           ti-brand-youtube   [badge: "soon"]
  
── CHANNELS ──
  Channels           ti-tv   [badge: "soon"]
```

Active item: `active activemenu` classes on `<a class="sidebar-link dark-sidebar-link ...">`.

---

## Implementation Notes

- `StaffRequiredMixin`: custom mixin applying `@staff_member_required` via `method_decorator` on `dispatch`
- URL patterns unchanged — only view callables switch from functions to class `.as_view()`
- `nav_active` context variable replaces `nav_section` (rename for clarity)
- No migrations needed — purely frontend changes
- `just tailwind-build` still needed after any Tailwind class additions; `theme.css` is served as a static file separate from `tailwind.css`
- Add `.superpowers/` to `.gitignore`
