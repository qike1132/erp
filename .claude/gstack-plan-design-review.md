# /plan-design-review — Designer's Eye Plan Review (Comate Adapted)

> Rate each design dimension 0-10, explain what a 10 looks like, then fix the plan.

## Step 0: Prerequisite Check

If no design doc exists, offer `/office-hours` first.

## Design Philosophy & Principles

1. **Subtraction default** — If you can't justify why something is there, remove it
2. **Hierarchy as service** — Visual hierarchy serves comprehension, not decoration
3. **Edge case paranoia** — Design for empty states, errors, long text, slow networks
4. **Progressive disclosure** — Show only what's needed now, reveal on demand
5. **Consistency over creativity** — Predictable beats novel (except when novel IS the product)
6. **Accessibility is not optional** — Design for the edges, the center takes care of itself
7. **Motion with purpose** — Animation explains, never decorates
8. **Mobile gravity** — Design mobile-first; constraints create clarity
9. **One thing per screen** — Each view has one primary action

## Review Process

### Pass 1: Rate Each Dimension

For each design dimension, rate 0-10 using the **gap method**:
- State the current score
- Explain what a 10 looks like (the gold standard)
- Identify what's missing between current and 10

| Dimension | What to evaluate |
|-----------|-----------------|
| Visual Hierarchy | Can users instantly identify the primary action? |
| Information Architecture | Is navigation predictable? Can users find what they need in <3 clicks? |
| Typography | Does type scale create clear reading hierarchy? |
| Color System | Do colors communicate meaning? Is contrast sufficient? |
| Spacing & Layout | Does whitespace guide the eye? Is density appropriate? |
| Interaction Design | Are affordances clear? Do states communicate? |
| Error Handling | Are errors helpful? Can users recover easily? |
| Empty States | Is there guidance when there's nothing to show? |
| Responsive Behavior | Does it work well at every breakpoint? |
| Accessibility | Can all users complete core tasks? |
| Loading States | Are wait times managed? Is progress visible? |
| Onboarding | Can new users succeed in <5 minutes? |

### Pass 2: Fix Toward 10

For each dimension scoring <8:
1. Write specific design recommendations
2. Prioritize: which fixes have the biggest impact?
3. Add these to the plan as design decisions

### UX Principles to Apply

- **Three Laws of Usability**: Don't make me think, It doesn't matter how many times I click as long as each click is a mindless choice, Get rid of half the words, then get rid of half of what's left
- **Scanning behavior**: Users scan in F-pattern, put important things at scan points
- **Billboard design**: Users glance, don't read — design for 3-second comprehension
- **Navigation wayfinding**: Users always need to know where they are, where they came from, where they can go
- **Goodwill reservoir**: Every frustration depletes goodwill; every delight restores it

## Output Format

```
## Design Review

### Dimension Scores
| Dimension | Score | Gap to 10 | Priority Fix |
|-----------|-------|-----------|-------------|
| Visual Hierarchy | 6 | Need clear CTA hierarchy | HIGH |
| ... | ... | ... | ... |

### Critical Design Decisions (add to plan)
1. [Decision] — [Rationale] — [Impact on score]
```

## Proactive Trigger Rules

Invoke this skill when:
- User asks "review the UX/design of this plan"
- Before implementing a UI-heavy feature
- User says "check design decisions"
