# Frontend Terminology Migration (Development Phase)

## Overview

This is a **development-phase terminology change** where the frontend has been updated to use clearer, simpler language:
- "department" → "channel" (organizational grouping)
- "process" → "agent" (individual workflow instance)

The backend remains unchanged to minimize coordination overhead during development.

## Scope

This migration affects **frontend only**. The backend Django models, API contracts, and database schema remain unchanged.

## What Changed

### Channel Terminology (department → channel)
- **Directory structure**: `app/departments/` → `app/channels/`
- **Type definitions**: `Department` → `Channel` in `lib/types.ts`
- **Imports & variables**: `department`/`departmentId` → `channel`/`channelId`
- **Files updated**: Sidebar, page components, process agent detail view

### Agent Terminology (process → agent)
Pure UI label changes (type names stay as `ProcessAgent*` for internal consistency):
- **UI labels**: "Add Process" → "Add Agent", "View Process" → "View Agent"
- **Form fields**: "Process *" → "Agent *", "Select a process" → "Select an agent"
- **Status messages**: "This process is…" → "This agent is…"
- **Modal steps**: "Step 1 — Select process" → "Step 1 — Select agent"
- **Empty states**: "This channel has no processes" → "This channel has no agents"
- **Files updated**:
  - `app/channels/[id]/page.tsx` (Add Agent buttons, empty state)
  - `app/process-agents/[id]/page.tsx` (status label, not-found message)
  - `app/process-agents/new/page.tsx` (title)
  - `app/leads/page.tsx` (select dropdown, View Agent link)
  - `app/settings/page.tsx` (wizard reference)
  - `components/leads/UploadCampaignModal.tsx` (field label, step title, option text)

### Adapter Layer (`lib/telehubApi.ts`)
Added mapping functions:
- `mapChannelToBackend()`: Converts frontend `channelId` → backend `department` before sending
- `mapBackendToChannel()`: Converts backend `department` → frontend `channel` after receiving

All public API functions now use the adapter to transparently handle the terminology mismatch.

## Why This Approach?

### Channels (Department → Channel)
- **Low risk**: Isolated frontend change, no database migrations needed
- **Backwards compatible**: Backend unchanged, no coordinated deploy required
- **Clear boundary**: Adapter layer makes the mismatch explicit and easy to audit

### Agents (Process → Agent)
- **Cosmetic only**: Pure UI/label changes, no type system impact (ProcessAgent* types unchanged)
- **Cleaner language**: Shorter, simpler labels reduce UI clutter and improve clarity
- **Reversible**: No infrastructure changes; easy to revert if needed

## Production Path

### Channels (Development Phase)
**This is temporary.** Before moving to production, choose one of:

1. **Rename backend**: Migrate Django models `Department` → `Channel`, update all API contracts. Requires database migration and full test suite rerun.
2. **Revert frontend**: Keep backend terminology, revert frontend to use "department" throughout.

The adapter layer makes this decision **reversible**—removing it is straightforward once you've chosen the path.

### Agents (Cosmetic UI Change)
The "process" → "agent" renaming is purely cosmetic UI labels with zero backend impact. It can be:
- **Kept as-is** through production (no risk)
- **Extended to backend** if channel terminology is also updated (requires migration)
- **Reverted** if feedback suggests it's confusing (trivial to undo)

## Testing

- **Routes**: `/channels/` instead of `/departments/`
- **API calls**: Internally reference `department` (backend unchanged)
- **Database**: No changes; existing data unaffected
- **Type system**: `ProcessAgent*` types unchanged; adapter handles mapping at boundaries
- **UI labels**: Updated across all workflow creation and management flows
- **Backward compatibility**: All existing tests pass with adapter transparency

## Files Modified

**Directory structure:**
- `app/departments/` → `app/channels/`

**Channels terminology (department → channel):**
- `lib/types.ts` - Type definitions
- `lib/telehubApi.ts` - Adapter layer + API functions
- `components/Sidebar.tsx` - Navigation
- `app/channels/page.tsx` & `app/channels/[id]/page.tsx`
- `app/process-agents/[id]/page.tsx` & `app/process-agents/new/page.tsx`
- `app/leads/page.tsx`
- `components/leads/UploadCampaignModal.tsx`
- `app/page.tsx`

**Agents terminology (process → agent, UI labels only):**
- `app/channels/[id]/page.tsx` - "Add Agent" buttons, empty state
- `app/process-agents/[id]/page.tsx` - Status label, error message
- `app/process-agents/new/page.tsx` - Page title
- `app/leads/page.tsx` - Select dropdown, view link
- `app/settings/page.tsx` - Wizard reference
- `components/leads/UploadCampaignModal.tsx` - Field label, step title, option text
