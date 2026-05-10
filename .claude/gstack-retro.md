# /retro — Weekly Engineering Retrospective (Comate Adapted)

> Analyze commit history, work patterns, and code quality metrics with persistent history and trend tracking. Team-aware: breaks down per-person contributions with praise and growth areas.

## Step 1: Time Range

Default: last 7 days. Ask if user wants a different range. For monthly retros, use 28-31 days.

## Step 2: Commit History Analysis

Gather the data:

```
# Overall stats
git log --since="7 days ago" --oneline | wc -l
git log --since="7 days ago" --shortstat

# Per-author breakdown
git shortlog -sn --since="7 days ago"

# Files changed
git diff --stat @{7.days.ago}

# Commit types (feature/fix/refactor/test/docs)
git log --since="7 days ago" --oneline | grep -c "feat"
git log --since="7 days ago" --oneline | grep -c "fix"
git log --since="7 days ago" --oneline | grep -c "refactor"
git log --since="7 days ago" --oneline | grep -c "test"
git log --since="7 days ago" --oneline | grep -c "docs"

# PRs merged
gh pr list --state merged --search "merged:>=2026-05-03" --json title,author,mergedAt

# Issues closed
gh issue list --state closed --search "closed:>=2026-05-03" --json title,assignee,closedAt
```

## Step 3: Per-Person Analysis

For each contributor, analyze:

**Volume metrics:**
- Number of commits
- Lines added / lines removed
- Files changed
- PRs opened / PRs merged

**Focus areas:**
- Which directories/files they worked on
- What types of work (features, fixes, refactoring, tests, docs)
- Cross-cutting work vs. deep-in-one-area

**Quality indicators:**
- Bug fixes introduced (commits that fix bugs in their own recent code)
- Test additions
- Code review participation (PRs reviewed)

**Praise** — specific, earned recognition:
- "Shipped [feature] in record time"
- "Caught [edge case] that would have been a production issue"
- "Refactored [module] and made it 3x more readable"

**Growth areas** — specific, actionable improvement:
- "Consider adding tests for [area] — 3 of the last 5 bugs were there"
- "Could benefit from more code review participation — reviewed 1 PR vs. 8 opened"
- "Try breaking PRs into smaller chunks — 3 PRs > 1000 lines"

## Step 4: Work Pattern Analysis

Identify patterns across the team:

**Velocity:**
- Total commits per day (trend: increasing, stable, decreasing?)
- PR cycle time (open to merge)
- Issue resolution time

**Distribution:**
- Is work evenly distributed? (Gini coefficient of commits)
- Are some people overloaded while others are idle?
- Are there single points of failure? (only one person knows system X)

**Health signals:**
- Ratio of features to fixes (trending toward more fixes = accumulating tech debt)
- Test coverage change
- Build success rate
- Commit message quality (conventional commits, descriptive)

## Step 5: Quality Metrics

- Test coverage change (if measurable)
- Number of bug fixes vs. features
- Code review participation (PRs reviewed / PRs opened per person)
- Build/deployment success rate
- Number of rollbacks or hotfixes
- Time from bug report to fix

## Step 6: Shipping Streaks

Track consecutive weeks with a meaningful ship:

```
### Shipping Streaks
| Contributor | Current Streak | Best Streak | Last Ship |
|------------|---------------|-------------|-----------|
| Alice | 4 weeks | 8 weeks | 2026-05-09 |
| Bob | 2 weeks | 6 weeks | 2026-05-08 |
| Carol | 0 weeks | 12 weeks | 2026-04-25 |
```

A "meaningful ship" is a merged PR that adds user-facing value or fixes a user-facing bug. Internal refactors don't count for the streak.

## Step 7: Retro Structure

### What Went Well
- [Specific achievement 1 — with evidence]
- [Specific achievement 2 — with evidence]
- Praise: [Specific person] for [specific contribution with context]

### What Could Improve
- [Specific issue 1 — with evidence, not blame]
- [Specific issue 2 — with evidence, not blame]
- Growth area: [Specific person] could [specific improvement] — [context, not judgment]

### Shipping Streak
- [Current streak status]

### Trend Tracking
- Compare with last retro: are we improving?
- Metrics that moved: velocity, quality, distribution

### Action Items
| # | Action | Owner | Due | Type |
|---|--------|-------|-----|------|
| 1 | [Action] | [Person] | [Date] | Process/Technical/Cultural |

## Step 8: Save Retro Notes

Save to `.gstack/retros/YYYY-MM-DD.md` with full content including:
- All metrics
- Per-person analysis
- Action items
- Trend comparison

## Step 9: Trend Tracking

Compare with previous retros:

```
### Trend (Last 4 Weeks)
| Metric | W1 | W2 | W3 | W4 | Trend |
|--------|----|----|----|----|-------|
| Commits/week | 45 | 52 | 48 | 61 | ↑ |
| Bug fix ratio | 20% | 25% | 30% | 22% | → |
| PR cycle time | 2d | 1.5d | 1d | 1.2d | ↓ (better) |
| Test coverage | 68% | 70% | 71% | 73% | ↑ |
```

## Important Rules

- **Praise must be specific and earned.** "Great job" is not praise. "Shipped the payment flow 2 days ahead of schedule, with 98% test coverage" is.
- **Growth areas must be actionable.** "Write better code" is not actionable. "Add tests for edge cases in the payment module — 3 of 5 bugs last week were there" is.
- **No blame.** "The API was slow because Bob wrote bad queries" → "API response times increased — we should add query performance monitoring to the CI pipeline."
- **Track trends, not snapshots.** A single week's data is noise. 4+ weeks of data is a signal.
- **Shipping streaks are motivational, not punitive.** Celebrate the streaks, don't shame the breaks.
