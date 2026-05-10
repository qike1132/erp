# /context-restore — Restore Saved Context (Comate Adapted)

> Resume from a saved context file, even across branches and Conductor workspace handoffs. Pair with /context-save.

## Commands

- `/context-restore` — Load most recent saved context (any branch)
- `/context-restore <title-or-number>` — Load a specific context
- `/context-restore list` — Show available saved contexts

## Restore Flow

### Step 1: Find Saved Contexts

```
# Find all checkpoint files, sorted newest first
ls -1 .gstack/checkpoints/*.md 2>/dev/null | sort -r | head -20
```

### Step 2: Load the Right File

- **Default:** load the most recent context (across ALL branches, not just current)
- **If `<title-or-number>` given:** match by title fragment or list number
- **If no contexts found:** "No saved contexts found. Use /context-save to create one."

Parse the YAML frontmatter and body content.

### Step 3: Branch Check

If current branch differs from saved branch, warn the user:

```
⚠️ BRANCH MISMATCH
Saved on: feature/auth
Currently on: main

Options:
A) Switch to feature/auth and continue
B) Stay on main and apply context
C) Just review the context, don't apply
```

### Step 4: Present Context Summary

Print a "RESUMING CONTEXT" block:

```
## RESUMING CONTEXT

**Title:** auth-refactor
**Branch:** feature/auth  ⚠️ Current branch differs (on: main)
**Saved:** 2026-05-10T14:30:00Z
**Status:** in_progress
**Commit:** abc1234 feat: add login endpoint
**Files modified:** 5 files
**Remaining items:** 3

### Summary
Implementing JWT authentication for the API layer

### Decisions Made
1. Using HS256 over RS256 — simpler for single-service deployment, no key management overhead
2. Storing refresh tokens in httpOnly cookies — prevents XSS access while allowing automatic refresh

### Remaining Work
- [ ] Add token refresh endpoint (src/api/auth.ts)
- [ ] Add auth middleware to protected routes (src/middleware/auth.ts)
- [ ] Write integration tests for login/refresh/logout flow

### Notes
- Tried RS256 first but key rotation was over-engineering for current scale
- Session approach rejected — stateful sessions don't scale horizontally
```

### Step 5: Restore Git State

If the user chose to restore:

1. **Check for uncommitted changes** on current branch — stash or warn
2. **Switch to saved branch** (if different)
3. **Verify the commit exists** — if the commit is gone (rebased), warn that state may have changed
4. **Show current diff** — so the user can see what's changed since the save

```
## Current State

**On branch:** feature/auth
**At commit:** abc1234 feat: add login endpoint
**Uncommitted changes:**
  M src/api/auth.ts (2 lines changed)
  ?? src/middleware/auth.ts (new file)
```

### Step 6: Offer Next Steps

Ask the user:
- A) Continue with remaining items (start with first unchecked task)
- B) Show full saved file (for more context)
- C) Just needed the context, I'll proceed on my own
- D) Mark as completed (update status to "completed")

### Step 7: Update Context File

After restoring, update the frontmatter:
- If continuing: status stays `in_progress`
- If completed: set status to `completed`
- Add `restored_at: <ISO-8601 timestamp>`

## List Flow

```
## Saved Contexts

| # | Title | Branch | Saved | Status | Files | Remaining |
|---|-------|--------|-------|--------|-------|-----------|
| 1 | auth-refactor | feature/auth | 2026-05-10 14:30 | in_progress | 5 | 3 |
| 2 | payment-fix | fix/payment-bug | 2026-05-09 11:20 | in_progress | 2 | 1 |
| 3 | docs-update | main | 2026-05-08 09:15 | completed | 4 | 0 |
```

Options:
- Default: show contexts for all branches
- `/context-restore list --branch` — filter to current branch only

## Important Rules

- **Default loads most recent across ALL branches.** You might be resuming work from a different branch.
- **Always warn on branch mismatch.** Don't silently switch branches.
- **Check for uncommitted changes before switching.** Stash or warn — don't lose work.
- **Verify commits exist.** A rebase or force-push could invalidate the saved state.
- **Context files are append-only.** Don't delete old contexts — they're useful for reference.
