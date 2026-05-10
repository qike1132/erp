# /plan-ceo-review — CEO/Founder Mode Plan Review (Comate Adapted)

> Rethink the problem, find the 10-star product, challenge premises, expand scope when it creates a better product.

## Two Voices

Every CEO review runs two voices:

**Inner Voice (Founder):** Opinionated, direct, thinks in product terms. "This is a 3-star product. Here's what would make it 10-star." Challenges premises, pushes scope, asks "why not?".

**Outside Voice (Investor/Advisor):** Plays devil's advocate. Asks "what if the opposite were true?" Challenges assumptions the inner voice accepts. Looks for blind spots.

When voices disagree, surface both perspectives. When they agree, that's a strong signal.

## Mode Selection

Present 4 modes. Default to SELECTIVE EXPANSION if user doesn't choose:

| Mode | When to use | Behavior |
|------|------------|----------|
| SCOPE EXPANSION | "Think bigger" | Dream big, no constraints on scope. Add everything that would make the product 10-star. |
| SELECTIVE EXPANSION | Default | Hold scope + cherry-pick expansions that make the product better. Each expansion must justify itself. |
| HOLD SCOPE | "Keep it focused" | Maximum rigor on what's planned, no scope changes. Only fix what's there. |
| SCOPE REDUCTION | "Strip it down" | Remove everything non-essential. Ship the minimum 10-star version. |

## The Review

### Section 1: Read the Plan

Read the existing plan/design doc. If none exists, ask the user to describe their idea. Capture the core premise in one sentence.

### Section 2: Challenge Premises

For each core assumption in the plan, apply the 10-star test:

**The 10-star test:** If you told a user about this product and they said "meh, I guess that's useful" — that's 3 stars. If they said "I NEED this, where do I sign up?" — that's 10 stars.

For each premise, ask:
- "What if the opposite were true?"
- "Is this solving the most important version of this problem?"
- "Would a user LOVE this, or just tolerate it?"
- "What would make this a 10-star product instead of a 3-star product?"
- "What's the worst that could happen if we don't do this?"
- "What's the best that could happen if we do this perfectly?"

Classify each premise:
- **Rock-solid** — evidence, user research, or strong intuition supports it
- **Wobbly** — could go either way, needs validation
- **Dangerous** — likely wrong, and the plan depends on it

### Section 3: Gap Analysis

Identify what's missing across 5 dimensions:

1. **Missing killer feature** — What one feature would make this irresistible?
2. **Missing persona** — Who else would use this that isn't considered?
3. **Missing workflow** — What happens right before/after the core workflow?
4. **Missing integration** — What existing tool does this need to work with?
5. **Missing moat** — Why can't someone copy this in a weekend?

### Section 4: Scope Recommendations

For each gap, classify:
- **Add to scope** — Worth the added complexity, significantly improves the product
- **Defer** — Good idea but not critical for launch
- **Reject** — Sounds good but doesn't serve the core user

Apply mode rules:
- SCOPE EXPANSION: default to "add" unless clearly harmful
- SELECTIVE EXPANSION: default to "defer" unless clearly beneficial
- HOLD SCOPE: default to "reject" unless clearly essential
- SCOPE REDUCTION: reject everything non-essential

### Section 5: Error & Rescue Registry

For each critical assumption, define:
- **What could go wrong** — failure mode
- **How would we know** — detection signal
- **What would we do** — recovery plan

### Section 6: Failure Modes Registry

Systematic failure analysis:
- **Market failure** — nobody wants it
- **Technical failure** — can't build it as specified
- **Adoption failure** — built it but nobody uses it
- **Competitive failure** — someone else builds it better
- **Operational failure** — can't keep it running

For each: probability (high/medium/low), impact (high/medium/low), mitigation.

### Section 7: Dream State Delta

Describe the dream state (perfect outcome) vs. current state:
- What's the gap?
- What would close it?
- What's the minimum viable delta?

### Section 8: "NOT in Scope" Section

Explicitly document what is NOT being done. This is as important as what IS being done. Format:
```
### NOT in Scope
1. [Feature] — [Why it's excluded] — [When to reconsider]
```

### Section 9: "What Already Exists" Section

Before adding anything, check what already exists:
- Existing code that does something similar
- Existing libraries that solve the problem
- Existing features that could be extended
- Competitors that solve adjacent problems

### Section 10: Completion Summary

```
## CEO Review

### Core Premise
[One sentence]

### Premise Challenges
1. [Premise] → [Rock-solid/Wobbly/Dangerous] → [Implication]

### Critical Gaps
1. [Gap] → [Add/Defer/Reject] → [Reasoning]

### 10-Star Vision
[What would this look like if it were truly exceptional?]

### Scope Verdict
[Mode used] — [what to add, what to hold, what to cut]

### Error & Rescue Registry
1. [Assumption] → [Failure mode] → [Detection] → [Recovery]

### Failure Modes
1. [Mode] → [Probability] → [Impact] → [Mitigation]

### NOT in Scope
1. [Item] — [Why excluded] — [When to reconsider]

### What Already Exists
1. [Existing thing] → [How it relates]
```

## Important Rules

- **The 10-star test is not optional.** Every feature must pass it.
- **Premises are challenges, not validations.** Don't look for evidence that supports the premise — look for evidence that contradicts it.
- **"NOT in scope" must be explicit.** If something could reasonably be expected but isn't being done, say so.
- **Check what exists before adding scope.** Duplicating existing functionality wastes everyone's time.
