# /autoplan — Auto Review Pipeline (Comate Adapted)

> One command runs CEO → design → eng → DX review sequentially with auto-decisions.

## Auto-decision Principles

When a review step would normally AskUserQuestion, autoplan decides using these 6 principles:

1. **Default to SELECTIVE EXPANSION** — For CEO review, hold scope + cherry-pick expansions
2. **Fix toward 8+** — For design review, auto-approve fixes that bring dimensions to 8+
3. **Block on BLOCKER** — For eng review, stop and surface BLOCKER issues; auto-approve SUGGESTION
4. **Triage friction** — For DX review, only surface BLOCKER friction; auto-fix speed bumps
5. **Preserve user intent** — If a decision changes user's stated direction, surface it
6. **Taste decisions surface** — Decisions with no clear "right answer" are collected for the final gate

## Pipeline Steps

### Step 1: CEO Review (`/plan-ceo-review`)
- Mode: SELECTIVE EXPANSION (auto-decided)
- Auto-approve: scope additions that strengthen the core product
- Surface: scope additions that change the product direction
- Output: CEO review findings

### Step 2: Design Review (`/plan-design-review`)
- Auto-approve: fixes that score <8 → 8+
- Surface: design decisions where multiple valid approaches exist
- Skip: if project has no UI/visual component
- Output: Design dimension scores + fixes

### Step 3: Engineering Review (`/plan-eng-review`)
- Auto-approve: SUGGESTION-level findings
- Block and surface: BLOCKER findings (security, data loss, correctness)
- Output: Eng review findings + architecture lock

### Step 4: DX Review (`/plan-devex-review`)
- Mode: DX POLISH (auto-decided)
- Auto-fix: speed bumps and paper cuts
- Surface: BLOCKER friction points
- Skip: if project is not developer-facing
- Output: DX scorecard + friction fixes

### Step 5: Final Approval Gate

Present ALL surfaced "taste decisions" in one consolidated prompt:

```
## Autoplan Complete

### Auto-applied (no action needed)
- CEO: <scope additions>
- Design: <dimension fixes>
- Eng: <suggestion fixes>
- DX: <friction fixes>

### Taste Decisions (need your input)
1. [CEO] <scope question> — Options: A) <...> B) <...>
2. [Design] <design choice> — Options: A) <...> B) <...>
3. [Eng] <architecture tradeoff> — Options: A) <...> B) <...>

### Blockers (must resolve)
1. [Eng] <blocker description> — <why it's blocking>
```

## Proactive Trigger Rules

Invoke this skill when:
- User says "run all reviews", "autoplan", "full review"
- User wants comprehensive review before starting implementation
