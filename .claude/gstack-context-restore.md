# /context-restore — Restore Saved Context (Comate Adapted)

> Resume from a saved context file, even across branches.

## Commands

- `/context-restore` — Load most recent saved context (any branch)
- `/context-restore <title-or-number>` — Load a specific context
- `/context-restore list` — Show available saved contexts

## Restore Flow

### Step 1: Find Saved Contexts

```bash
# Find all checkpoint files, sorted newest first
ls -1 .gstack/checkpoints/*.md 2>/dev/null | sort -r | head -20
```

### Step 2: Load the Right File

- Default: load the most recent context (across ALL branches, not just current)
- If `<title-or-number>` given: match by title fragment or list number
- If no contexts found: "No saved contexts found. Use /context-save to create one."

### Step 3: Present Context Summary

Print a "RESUMING CONTEXT" block:

```
## RESUMING CONTEXT

**Title:** <title>
**Branch:** <saved-branch>  ⚠️ Current branch differs (on: <current-branch>)
**Saved:** <timestamp>
**Status:** <status>
**Files modified:** <count> files

### Summary
<what was being worked on>

### Decisions Made
1. <decision>

### Remaining Work
- [ ] <task>
```

If current branch differs from saved branch, warn the user.

### Step 4: Offer Next Steps

Ask the user:
- A) Continue with remaining items
- B) Show full saved file
- C) Just needed the context, I'll proceed on my own

## Proactive Trigger Rules

Invoke this skill when:
- User says "resume", "restore context", "where was I"
- User says "pick up where I left off"
- Starting a new session and prior context exists
