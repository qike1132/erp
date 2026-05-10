# /context-save — Save Working Context (Comate Adapted)

> Save git state, decisions, and remaining work so any future session can resume — even across Conductor workspace handoffs. Pair with /context-restore to resume later.

## Commands

- `/context-save` — Save current context with auto-generated title
- `/context-save <title>` — Save with specific title
- `/context-save list` — Show all saved contexts for current branch

## Save Flow

### Step 1: Gather State

```
# Current branch
git branch --show-current

# Working tree status
git status --porcelain

# Diff stat (what's changed)
git diff --stat

# Staged changes
git diff --cached --stat

# Recent commit log
git log --oneline -10

# Uncommitted changes summary
git diff --name-only

# Current TODOS.md (if exists)
cat TODOS.md 2>/dev/null
```

### Step 2: Auto-Generate Title

If no title provided, generate from:
- Current branch name (most common source)
- Last commit message
- Modified files pattern

Examples:
- Branch `feature/auth` → "auth-refactor"
- Branch `fix/payment-bug` → "payment-bug-fix"
- No branch signal → use most-recent commit subject

### Step 3: Summarize Context

Construct a structured summary:

**What's being worked on:** 1-2 sentence description of the current task

**Decisions made:** Key architectural/implementation decisions from this session, with rationale:
1. [Decision] — [Why this approach was chosen over alternatives]

**Remaining work:** What still needs to be done, in order of priority:
- [ ] [Task with enough detail to resume without re-reading code]
- [ ] [Task with file references if applicable]

**Notes:** Anything a future session should know:
- Blockers and their current status
- Workarounds in place and why
- Things that were tried and failed
- Dependencies on other people/teams
- Time-sensitive information

### Step 4: Write Saved Context

Save to `.gstack/checkpoints/{YYYY-MM-DD-HHMMSS}-{title-slug}.md`:

```markdown
---
status: in_progress
branch: <branch-name>
saved_at: <ISO-8601 timestamp>
commit: <current-commit-hash>
files_modified:
  - path/to/file1
  - path/to/file2
files_staged:
  - path/to/staged-file
---

## Summary
<What's being worked on>

## Decisions Made
1. <Decision> — <Rationale>
2. <Decision> — <Rationale>

## Remaining Work
- [ ] <Task 1 — with file references>
- [ ] <Task 2 — with file references>

## Notes
<Anything a future session should know>

## Git State
- Branch: <branch>
- Last commit: <hash> <message>
- Modified files: <count>
- Staged files: <count>
```

### Step 5: Confirm

Print confirmation:
```
Context saved: <title>
Branch: <branch>
Commit: <hash>
Files modified: <count>
Remaining items: <count>
Location: .gstack/checkpoints/<filename>
Resume with: /context-restore
```

## List Flow

Display table of saved contexts:

```
## Saved Contexts (branch: feature/auth)

| # | Title | Saved | Status | Files | Remaining |
|---|-------|-------|--------|-------|-----------|
| 1 | auth-refactor | 2026-05-10 14:30 | in_progress | 5 | 3 |
| 2 | auth-tests | 2026-05-09 16:45 | completed | 2 | 0 |
```

Filter to current branch by default. Use `/context-save list --all` for all branches.

## Important Rules

- **Decisions must include rationale.** "Chose PostgreSQL" is useless without "over MongoDB because we need relational integrity for orders."
- **Remaining work must be resumable.** "Fix the bug" is not resumable. "Fix N+1 query in src/api/orders.ts:45 by adding eager loading for customer relation" is.
- **Notes must include failures.** If you tried approach A and it didn't work, say so — future-you shouldn't try it again.
- **Save before switching branches.** If you're about to context-switch, save first.
- **Include file paths.** Every task should reference specific files when possible.
