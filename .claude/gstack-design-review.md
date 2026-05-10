# /design-review — Live Site Visual Audit (Comate Adapted)

> Visual audit + fix loop. Rate each dimension, fix issues with atomic commits.

Note: The original gstack `/design-review` uses the browse binary for live screenshots. This Comate adaptation works with source code analysis instead.

## Step 1: Scope the Review

Ask the user:
- Which pages/views to review?
- Any specific concerns?
- What severity threshold? (All issues, or only MEDIUM+?)

## Step 2: Design Dimension Audit

Rate each dimension 0-10 using the gap method:

| Dimension | Quick Check |
|-----------|-------------|
| Visual Hierarchy | Can users identify the primary action in <1 second? |
| Spacing Consistency | Is spacing on a 4/8px grid? Are gaps consistent? |
| Color Usage | Do colors follow a defined system? Contrast ratios OK? |
| Typography | Is there a clear type scale? Consistent sizing? |
| Interactive States | Do all buttons/inputs have hover, focus, active, disabled? |
| Responsive | Does it work at every breakpoint? |
| Error States | Do forms show validation errors? Are they helpful? |
| Empty States | Is there content for no-data scenarios? |
| Loading States | Are there spinners/skeletons for async content? |
| Accessibility | ARIA labels, keyboard nav, screen reader support? |

## Step 3: Issue Triage

For each issue found:
- **Severity**: CRITICAL (broken) / HIGH (ugly) / MEDIUM (inconsistent) / LOW (nitpick)
- **Location**: specific file:line
- **Fix**: concrete CSS/HTML change

## Step 4: Fix Loop

For each issue (severity HIGH and above):
1. Fix with a targeted edit
2. Describe what was changed
3. Move to next issue

Make atomic commits for each fix: `fix(ui): <what was fixed>`

## Step 5: Summary

```
## Design Review Summary

### Scores
| Dimension | Before | After |
|-----------|--------|-------|
| Visual Hierarchy | 5 | 8 |
| Spacing | 4 | 7 |
| ... | ... | ... |

### Issues Found
- CRITICAL: 0
- HIGH: 3 (3 fixed)
- MEDIUM: 5 (2 fixed, 3 deferred)
- LOW: 8 (deferred)

### Commits
1. fix(ui): add focus-visible outlines to all buttons
2. fix(ui): normalize spacing to 4px grid
3. fix(ui): add empty state for order list
```

## Proactive Trigger Rules

Invoke this skill when:
- User asks "how does the UI look?"
- User wants visual polish
- After implementing a new UI component
