# Frontend Brief: Manual Clip Bypass

**For:** Claude Code running in the Reelforge Next.js frontend repository
**API base:** `/api/v1/`

---

## What changed on the backend

### New field on ClippingJob
- `skip_analysis: boolean` — writable at creation, readable on all responses

### New field on ClipCandidate
- `is_manual: boolean` — read-only; when `true` the candidate's `start_sec`/`end_sec` have no 30–180s restriction

### New API action
```
POST /api/v1/clipping/jobs/{id}/skip-to-candidates/
```
- No request body
- Returns: full job object (same shape as `GET /api/v1/clipping/jobs/{id}/`)
- 200: job → `AWAITING_CLIP_APPROVAL`, one `is_manual` candidate created
- 400: `{"detail": "Cannot skip to candidates from state {status}."}` — invalid state

---

## Changes needed

### 1. New Job form (`/clipping/jobs/new`)

Add a "Skip AI analysis" toggle below the source type selector:

```tsx
<div className="flex items-center gap-3">
  <Switch
    id="skip-analysis"
    checked={form.watch("skip_analysis")}
    onCheckedChange={(val) => form.setValue("skip_analysis", val)}
  />
  <Label htmlFor="skip-analysis" className="flex flex-col gap-0.5">
    <span>Skip AI analysis</span>
    <span className="text-xs text-muted-foreground font-normal">
      Upload a pre-edited video and go directly to the clip configure stage
    </span>
  </Label>
</div>
```

Add `skip_analysis: z.boolean().default(false)` to the form schema and include it in the POST body.

### 2. Job list / job detail

- Show `<Badge variant="secondary">Manual</Badge>` on jobs where `skip_analysis === true`
- On jobs with status `TRANSCRIBING`, `ANALYZING`, or `FAILED`, show a "Skip to candidates" button:

```tsx
<Button variant="outline" size="sm" onClick={() => handleSkip(job.id)} disabled={isSkipping}>
  {isSkipping ? "Skipping…" : "Skip to candidates"}
</Button>
```

Handler:
```ts
async function handleSkip(jobId: string) {
  setIsSkipping(true)
  try {
    const res = await fetch(`/api/v1/clipping/jobs/${jobId}/skip-to-candidates/`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) {
      toast.error((await res.json()).detail ?? "Failed")
      return
    }
    await refetchJob()  // or queryClient.invalidateQueries(["job", jobId])
    toast.success("Job fast-forwarded to candidate stage")
  } finally {
    setIsSkipping(false)
  }
}
```

### 3. Candidate card / configure page

- Show `<Badge variant="outline">Manual clip</Badge>` when `is_manual === true`
- When `is_manual === true`, render `start_sec` and `end_sec` as editable inputs (currently read-only):

```tsx
{candidate.is_manual && (
  <div className="grid grid-cols-2 gap-3">
    <div>
      <Label>Start (seconds)</Label>
      <Input type="number" step="0.1" min="0" value={startSec}
        onChange={e => setStartSec(parseFloat(e.target.value))}
        onBlur={() => patchCandidate({ start_sec: startSec })} />
    </div>
    <div>
      <Label>End (seconds)</Label>
      <Input type="number" step="0.1" min="0" value={endSec}
        onChange={e => setEndSec(parseFloat(e.target.value))}
        onBlur={() => patchCandidate({ end_sec: endSec })} />
    </div>
  </div>
)}
```

`patchCandidate` → `PATCH /api/v1/clipping/candidates/{id}/` with updated fields. No frontend validation needed for `is_manual` candidates — the backend has no duration/overlap constraints on them.

---

## Testing checklist

- [ ] New job form: toggle appears, defaults off, sets `skip_analysis: true` on submit
- [ ] Job list: `skip_analysis: true` jobs show "Manual" badge
- [ ] Job detail: TRANSCRIBING/ANALYZING/FAILED jobs show "Skip to candidates" button
- [ ] Button: calls API, refreshes job, shows success toast
- [ ] Button: 400 error surfaces backend message in toast
- [ ] Candidate card: `is_manual: true` shows "Manual clip" badge
- [ ] Configure page: `is_manual: true` unlocks `start_sec`/`end_sec` inputs
- [ ] Configure page: `is_manual: false` keeps times read-only
