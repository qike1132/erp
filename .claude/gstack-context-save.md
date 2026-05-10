# /context-save — Save Working Context (Comate Adapted)

> Save git state, decisions, and remaining work so any future session can resume.

## Commands

- `/context-save` — Save current context with auto-generated title
- `/context-save <title>` — Save with specific title
- `/context-save list` — Show all saved contexts for current branch

## Save Flow

### Step 1: Gather State

```bash
# Current branch
git branch --show-current

# Working tree status
git status --porcelain

# Diff stat (what's changed)
git diff --stat

# Recent commit log
git log --oneline -10

# Uncommitted changes summary
git diff --name-only
```

### Step 2: Summarize Context

Construct a structured summary:
- **What's being worked on**: 1-2 sentence description
- **Decisions made**: Key architectural/implementation decisions from this session
- **Remaining work**: What still needs to be done
- **Notes**: Anything a future session should know (blockers, workarounds, etc.)

### Step 3: Write Saved Context

Save to `.gstack/checkpoints/{YYYY-MM-DD-HHMMSS}-{title-slug}.md`:

```markdown
---
status: in_progress
branch: <branch-name>
saved_at: <ISO-8601 timestamp>
files_modified:
  - path/to/file1
  - path/to/file2
---

## Summary
<What's being worked on>

## Decisions Made
1. <Decision> — <Rationale>
2. <Decision> — <Rationale>

## Remaining Work
- [ ] <Task 1>
- [ ] <Task 2>

## Notes
<Anything a future session should know>
```

### Step 4: Confirm

Print confirmation:
```
Context saved: <title>
Branch: <branch>
Files modified: <count>
Remaining items: <count>
Resume with: /context-restore
```

## List Flow

Display table of saved contexts:

| # | Title | Branch | Saved | Status |
|---|-------|--------|-------|--------|
| 1 | auth-refactor | feature/auth | 2026-05-10 14:30 | in_progress |

Filter to current branch by default. Use `/context-save list --all` for all branches.

## Proactive Trigger Rules

Invoke this skill when:
- User says "save progress", "save state", "save my work"
- User is about to leave or end a session
- User says "I'll come back to this later"
