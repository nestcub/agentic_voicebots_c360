# Intelligence Frontend Redesign + Bugfix — Build Handoff

> Handoff spec for implementation. Frontend-only (Next.js dashboard). **The backend is
> untouched** — every endpoint referenced already exists and works. Scope: fix the transcript
> history bug, restructure Intelligence into 3 tabs (Transcribe · Build · Knowledge), rebuild the
> sidebar in the light Chat360 style, and build a split-view "Build" workspace that merges the old
> Design + Plans pages.

---

## 1. Context & Goals

The Intelligence section has four loosely-connected pages (Transcribe, Design, Plans, Knowledge)
and a dark sidebar that doesn't match the real Chat360 product (light/white sidebar). Three drivers:

1. **Bug:** clicking a transcript in history renders nothing.
2. **IA:** Design + Plans are one workflow (generate a plan via chat, then browse/patch its versions)
   and should merge into a single **Build** workspace.
3. **Visual:** sidebar should match the real Chat360 UI — light/white, logo, blue active pill,
   expandable Intelligence group.

**End state:** 3-tab Intelligence (**Transcribe · Build · Knowledge**), light Chat360 sidebar,
split-view Build (chat + live plan artifact + version history + knowledge drawer), fixed viewer.

**Confirmed product decisions:**
- 3-tab nav. Knowledge is **both** a standalone tab (full management) **and** a side-drawer inside
  Build (read + quick-approve while building).
- Light/white sidebar matching the screenshots.
- Build = split layout: chat on the left, plan artifact on the right.

---

## 2. Design System (reuse — do not reinvent)

- **Primitives:** `Card`, `CardHeader` — `dashboard/components/Card.tsx`
  (`Card` = `bg-white rounded-xl shadow-sm border border-gray-100`).
- **Icons:** `react-icons/ri` (Remix). Nav icons `w-5 h-5`, compact `w-4 h-4`.
- **Palette** (`dashboard/app/globals.css`, Tailwind v4 `@theme`): primary `#2563eb` (blue-600);
  page bg gray-50 (`#f9fafb`); surface `bg-white`; text gray-800 / gray-500 / gray-400; borders
  gray-100 / gray-200. Status: emerald (ok) / amber (warn) / rose (bad). Font: Inter.
  There is a `.flash-row` keyframe (amber pulse) — reuse it for the "section changed" flash.
- **Typography:** page title `text-lg font-semibold text-gray-800`; card title
  `text-base font-semibold text-gray-800`; hint `text-xs text-gray-400`; body `text-sm`.
- **Proxy:** the browser calls `/api/intelligence/<path>`; `dashboard/app/api/intelligence/[...path]/route.ts`
  forwards to the backend (`INTEL_API_URL`, default `http://localhost:8001`) injecting `x-api-key`.
  **New Build page must use `/api/intelligence/...`** (the existing design page already does).
  Note: the transcribe page currently calls the backend directly via
  `NEXT_PUBLIC_INTEL_API_URL` — leave that as-is (it works); don't churn it.
- **Layout shell:** `dashboard/components/LayoutShell.tsx` (Sidebar + TopHeader + main). Sidebar
  collapse state via `dashboard/context/SidebarContext.tsx` (`useSidebar().isOpen`, `.toggle()`).

---

## 3. Backend API Contracts (already live — for reference only)

All via the `/api/intelligence/*` proxy.

| Method & path | Request | Response |
|---|---|---|
| `POST /converse` | `{client_id, message}` | `{reply, use_case, mode, plan, plan_id, plan_changed, diff, version}` |
| `GET /plans?client_id=` | — | `[{id, client_id, version, plan, created_at, updated_at}]` (most-recent first) |
| `GET /plans/{id}` | — | `{id, client_id, version, plan, created_at, updated_at}` |
| `GET /plans/{id}/patches` | — | `[{id, plan_id, version, admin_request, patch, llm_reasoning, created_at}]` (version ASC) |
| `GET /transcripts?client_id=` | — | `[{id, filename, duration, created_at}]` |
| `GET /transcripts/{id}` | — | `{id, client_id, filename, transcript_text, segments, duration, created_at}` |
| `GET /transcripts/{id}/insights` | — | insight row (see below) or 404 |
| `PATCH /transcripts/{id}` | `{text}` | re-extracted insight dict |
| `GET /knowledge?status=active\|pending` | — | `[{id, topic, fact, source, status, created_at}]` |
| `PATCH /knowledge/{id}` | `{status}` | `{ok:true}` |

**`converse()` semantics (drives the Build UI):**
- `mode ∈ {use_case, plan, patch, advice, rescan}`.
- First plan: `mode="plan"`, `plan_changed=true`, `plan` = full plan, `version=1`.
- Change: `mode="patch"`, `plan_changed=true`, `diff = {key: {before, after}}` for **only the changed
  top-level keys**, `plan` = full merged plan, `version` incremented.
- Advice: `mode="advice"`, `plan_changed=false`, `plan` may be null.

**Plan object shape** (top-level keys to render as artifact sections):
`workflow_blueprint` (`{description, stages:[{stage_id,name,node_type,purpose,chat360_config}]}`),
`system_prompt` (string), `qualification_questions` (`[{question,variable,purpose}]`),
`objection_handling` (`{objection: response}`), `escalation_rules` (`[{trigger,action,node_type}]`),
`kb_scaffold` (`{topic: content}`), `build_notes` (`{canvas_instructions[], variables_required[], …}`).

**Insight row shape:** top-level `agent_score`, `sentiment`, `objection_patterns`,
`qualification_signals`, `escalation_signals`, `kb_gaps`, `summary`, plus `raw_insights_json`
(the full LLM output). ⚠️ `bot_failure_modes` and `suggested_fixes` are **only inside
`raw_insights_json`**, not top-level columns.

---

## 4. Task 1 — Fix the transcript viewer

**File:** `dashboard/app/intelligence/transcribe/page.tsx`

**Root cause:** the viewer is nested inside `{showQueue && (...)}` at **line 416**
(`showQueue = fileItems.length > 0`, line 320). Clicking a history row calls `loadTranscript()`
(line 266) which sets `viewingTranscript`, but when no files were uploaded this session the grid
isn't mounted, so nothing renders.

**Fix:**
1. Restructure the lower region into an **always-present** `grid md:grid-cols-2 gap-6`:
   - **Left column:** render the **Queue** card when `showQueue`; otherwise render the **History**
     card here (move History out from the bottom into this column when no active queue, or keep a
     single History card that's always visible — either works, but the viewer must not depend on it).
   - **Right column:** the **Transcript viewer** card, rendered whenever
     `viewingTranscript || loadingViewer` — **independent of `fileItems`**.
2. In `loadTranscript()` add error surfacing: if `tRes` is not `ok`, set a `viewerError` state and
   render it in the viewer (currently the failure is silent inside the `try`).
3. Insights resilience — when reading the two nested lists, fall back to `raw_insights_json`:
   ```ts
   const botFailureModes = viewingInsights.bot_failure_modes ?? viewingInsights.raw_insights_json?.bot_failure_modes ?? [];
   const suggestedFixes  = viewingInsights.suggested_fixes  ?? viewingInsights.raw_insights_json?.suggested_fixes  ?? [];
   ```
   Use these in the existing list-rendering block (lines ~570–610). No backend change.

**Acceptance:** fresh session (no uploads) → click a history row → transcript text + segments +
insights all render; a fetch failure shows an inline error; edit + Save & Re-analyse refreshes insights.

---

## 5. Task 2 — Light Chat360 sidebar

**File:** `dashboard/components/Sidebar.tsx` (rewrite)

- Container `bg-white border-r border-gray-200 text-gray-700` (was `bg-[#1a2535] text-white`).
- Logo row: `Chat` + `<span class="text-blue-600">360</span>`, with the collapse toggle
  (`RiMenuFoldLine` / `RiMenuUnfoldLine`) preserved.
- Nav item — inactive: `text-gray-600 hover:bg-gray-100`; **active: `bg-blue-600 text-white`**
  rounded-lg (matches the "Home" active state in the screenshots). Icon inherits text color.
- **Expandable Intelligence group:** the `/intelligence` entry becomes a parent row that toggles a
  sub-list — **Transcribe** (`/intelligence/transcribe`, `RiMicLine`), **Build**
  (`/intelligence/build`, `RiHammerLine` or `RiFlowChart`), **Knowledge**
  (`/intelligence/knowledge`, `RiBookOpenLine`). Use local `useState` for open/closed; auto-open
  when `pathname.startsWith("/intelligence")`. Show a chevron (`RiArrowDownSLine`/`RiArrowUpSLine`).
  Sub-item active state = same blue pill (or a lighter `bg-blue-50 text-blue-600` for hierarchy).
- Respect collapsed mode (`useSidebar().isOpen === false`): show icons only, labels via `title`;
  the group can expand on click or show sub-items on hover.
- Keep the existing footer ("AI Orchestrator · live") restyled for light bg
  (`text-gray-400 border-t border-gray-200`).
- If any token references the old dark sidebar (`--color-sidebar-bg` in `globals.css`,
  `TopHeader` borders), align them to the light theme. TopHeader is already white — likely no change.

**Acceptance:** white sidebar, Chat360 logo, blue active pill; Intelligence expands to the three
sub-items; collapse toggle still works.

---

## 6. Task 3 — Build workspace (merges Design + Plans)

**New file:** `dashboard/app/intelligence/build/page.tsx`
**New components:** `dashboard/components/intelligence/ChatThread.tsx`,
`dashboard/components/intelligence/PlanArtifact.tsx`

All network calls via `/api/intelligence/...`. `client_id` from `localStorage("intel_client_id")`
(same pattern as the other Intelligence pages).

### Layout — split (`grid md:grid-cols-2`, or `lg:grid-cols-[1fr_1.2fr]`)

**Left column — Chat (`ChatThread`):**
- Message thread of `{role:"user"|"assistant", content}` bubbles — reuse the existing design page's
  bubble styling (`dashboard/app/intelligence/design/page.tsx` lines ~73–86).
- Input + Send → `POST /api/intelligence/converse {client_id, message}`. Append the user turn
  immediately, then the assistant `reply` on response.
- On each response, lift `{plan, plan_id, diff, version, plan_changed, mode}` to the page so the
  artifact updates.
- On mount, hydrate the artifact from the latest plan: `GET /plans?client_id=` → take the first
  (most recent) → `GET /plans/{id}`. (No turns endpoint exists, so the chat log starts fresh each
  session; the plan persists.)

**Right column — Plan artifact (`PlanArtifact`):**
- Header: `Plan v{version}` + a **Current / History** segmented toggle.
- **Current view:** collapsible sections, one per plan top-level key — `workflow_blueprint`
  (render `description` + a `stages` list), `system_prompt` (mono block), `qualification_questions`,
  `objection_handling`, `escalation_rules`, `kb_scaffold`, `build_notes`. Reuse the collapsible
  `<Section>` pattern from the old Plans page (`dashboard/app/intelligence/plans/page.tsx`).
  - On a patch turn, the keys present in `diff` get a **"changed" chip** and a one-shot flash
    (`.flash-row` from `globals.css`); clicking the chip expands a **before/after** view from
    `diff[key].before` / `diff[key].after`.
- **History view:** version timeline from `GET /plans/{id}/patches` — each row: `v{version}`,
  `admin_request` (what the user asked), `llm_reasoning` (what changed), and the patch diff.
  This replaces the standalone Plans page.

**Knowledge side-drawer (in Build):**
- A book-icon button (top-right of the artifact panel) toggles a slide-over panel.
- Lists active facts (`GET /api/intelligence/knowledge?status=active`) and pending facts; pending
  rows get an **Approve** button → `PATCH /api/intelligence/knowledge/{id} {status:"active"}`.
- Read-mostly; full add/edit/delete stays in the Knowledge tab.

**Acceptance:** type a use case → first plan fills the artifact (collapsible sections); ask for a
change → assistant reply + only the changed section(s) flash/show a diff; History lists versions
with diffs; the knowledge drawer opens and quick-approve works.

---

## 7. Task 4 — Repoint nav + retire old pages

- **Hub** `dashboard/app/intelligence/page.tsx`: change the quick-nav grid from 4 cards to **3**
  (Transcribe, Build, Knowledge). Keep the Recent Transcripts / Recent Plans activity lists; point
  "Recent Plans" rows at `/intelligence/build`.
- **Redirects:** convert `dashboard/app/intelligence/design/page.tsx` and
  `dashboard/app/intelligence/plans/page.tsx` into thin client redirects to `/intelligence/build`
  (`"use client"` + `useRouter().replace("/intelligence/build")` in a `useEffect`) so existing
  links/bookmarks don't 404.

---

## 8. File Checklist

| File | Action |
|---|---|
| `dashboard/app/intelligence/transcribe/page.tsx` | Fix viewer render guard + insights `raw_insights_json` fallback + error surfacing |
| `dashboard/components/Sidebar.tsx` | Rewrite: light theme + expandable Intelligence group |
| `dashboard/app/intelligence/build/page.tsx` | **New** — split workspace |
| `dashboard/components/intelligence/ChatThread.tsx` | **New** — chat column |
| `dashboard/components/intelligence/PlanArtifact.tsx` | **New** — artifact (Current/History + diff highlight) |
| `dashboard/app/intelligence/page.tsx` | Hub → 3 cards; Recent Plans → Build |
| `dashboard/app/intelligence/design/page.tsx` | → redirect to `/intelligence/build` |
| `dashboard/app/intelligence/plans/page.tsx` | → redirect to `/intelligence/build` |
| `dashboard/app/globals.css` / `TopHeader.tsx` | Only if a sidebar token needs the light theme |

**Parallelization (non-overlapping):** (A) Sidebar · (B) Build page + ChatThread + PlanArtifact ·
(C) Transcribe bugfix · (D) hub + redirects. A/C/D are independent; B is the largest.

---

## 9. Verification

1. `cd dashboard && npx tsc --noEmit` → clean.
2. `cd dashboard && npm run dev`; backend intelligence API running on `:8001`.
3. **Bug:** `/intelligence/transcribe`, fresh session, click a history row → viewer renders
   transcript + segments + insights; fetch failure shows an inline error.
4. **Sidebar:** white bg, Chat360 logo, blue active pill; Intelligence expands to Transcribe/Build/
   Knowledge; collapse toggle works.
5. **Build:** use case → first plan in artifact; change request → reply + only changed sections
   flash + diff; History lists versions; knowledge drawer opens + quick-approve works.
6. **Routing:** `/intelligence/design` and `/intelligence/plans` redirect to `/intelligence/build`;
   hub shows 3 cards.
</content>
