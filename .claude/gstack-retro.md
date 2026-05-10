# /retro — Weekly Engineering Retrospective (Comate Adapted)

> Analyze commit history, work patterns, and code quality with per-person breakdowns.

## Step 1: Time Range

Default: last 7 days. Ask if user wants a different range.

## Step 2: Commit History Analysis

```bash
# Overall stats
git log --since="7 days ago" --oneline | wc -l
git log --since="7 days ago" --shortstat

# Per-author breakdown
git shortlog -sn --since="7 days ago"

# Files changed
git diff --stat @{7.days.ago}
```

## Step 3: Work Pattern Analysis

For each contributor:
- Number of commits
- Lines added/removed
- Areas of focus (which directories/files)
- Types of work (features, fixes, refactoring, tests, docs)

## Step 4: Quality Metrics

- Test coverage change (if measurable)
- Number of bug fixes vs features
- Code review participation
- Build/deployment success rate

## Step 5: Retro Structure

### What Went Well
- [Specific achievement 1]
- [Specific achievement 2]
- Praise: [Specific person] for [specific contribution]

### What Could Improve
- [Specific issue 1]
- [Specific issue 2]
- Growth area: [Specific person] could [specific improvement]

### Shipping Streak
- Track consecutive weeks with meaningful ship

### Action Items
| # | Action | Owner | Due |
|---|--------|-------|-----|
| 1 | [Action] | [Person] | [Date] |

## Step 6: Save Retro Notes

Save to `.gstack/retros/YYYY-MM-DD.md`

## Proactive Trigger Rules

Invoke this skill when:
- User asks for a retrospective
- End of week/sprint
- User asks "how did we do this week?"
