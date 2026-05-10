# /plan-design-review — Designer's Eye Plan Review (Comate Adapted)

> Rate each design dimension 0-10, explain what a 10 looks like, then fix the plan toward 10. Works in plan mode (before implementation). For live site visual audits, use /design-review.

## Step 0: Prerequisite Check

If no design doc exists, offer `/office-hours` first. A design review without a design doc is premature.

## 7 Review Passes

The review runs in 7 sequential passes. Each pass must complete before the next begins.

### Pass 1: Rate Each Dimension (0-10 Gap Method)

For each of the 12 design dimensions, rate using the **gap method**:
1. State the current score (0-10)
2. Explain what a 10 looks like (the gold standard)
3. Identify what's missing between current and 10

| # | Dimension | What to evaluate | 10-star gold standard |
|---|-----------|-----------------|----------------------|
| 1 | Visual Hierarchy | Can users instantly identify the primary action? | Single dominant CTA, clear visual weight order, no ambiguity about what to do next |
| 2 | Information Architecture | Is navigation predictable? Can users find what they need in <3 clicks? | Flat hierarchy, predictable groupings, search finds everything |
| 3 | Typography | Does type scale create clear reading hierarchy? | 4+ distinct levels, consistent scale ratio, body text 16px+, line-height 1.5+ |
| 4 | Color System | Do colors communicate meaning? Is contrast sufficient? | Semantic color mapping, 4.5:1+ contrast, works in dark mode |
| 5 | Spacing & Layout | Does whitespace guide the eye? Is density appropriate? | 4/8px grid, consistent gaps, breathing room around CTAs |
| 6 | Interaction Design | Are affordances clear? Do states communicate? | Hover/focus/active/disabled on all interactives, loading states, transitions |
| 7 | Error Handling | Are errors helpful? Can users recover easily? | Inline validation, clear fix instructions, never lose user data |
| 8 | Empty States | Is there guidance when there's nothing to show? | Illustration + action prompt, never blank white space |
| 9 | Responsive Behavior | Does it work well at every breakpoint? | Mobile-first, no horizontal overflow, touch targets 44px+ |
| 10 | Accessibility | Can all users complete core tasks? | WCAG 2.1 AA, keyboard navigable, screen reader friendly |
| 11 | Loading States | Are wait times managed? Is progress visible? | Skeleton screens, progress bars, optimistic updates |
| 12 | Onboarding | Can new users succeed in <5 minutes? | Guided tour, smart defaults, zero-config start |

### Pass 2: Design Hard Rules

Check each rule. Violation = auto-fix (not taste decision):

1. **Subtraction default** — If you can't justify why something is there, remove it
2. **Hierarchy as service** — Visual hierarchy serves comprehension, not decoration
3. **Edge case paranoia** — Design for empty states, errors, long text, slow networks
4. **Progressive disclosure** — Show only what's needed now, reveal on demand
5. **Consistency over creativity** — Predictable beats novel (except when novel IS the product)
6. **Accessibility is not optional** — Design for the edges, the center takes care of itself
7. **Motion with purpose** — Animation explains, never decorates
8. **Mobile gravity** — Design mobile-first; constraints create clarity
9. **One thing per screen** — Each view has one primary action

**Classifier for each rule:** PASS / VIOLATION (auto-fix) / BORDERLINE (taste decision)

### Pass 3: AI Slop Blacklist

Check for these 11 AI-generated design anti-patterns:

1. **Gradient soup** — gradients on everything without semantic purpose
2. **Card-itis** — every element wrapped in a card with rounded corners and shadow
3. **Purple haze** — defaulting to purple/violet without brand justification
4. **Hero inflation** — massive hero sections with generic stock imagery
5. **Icon salad** — adding icons that don't add information
6. **Animation bloat** — animating everything because you can
7. **Whitespace desert** — too much padding creating disconnected experiences
8. **Font overload** — 3+ font families without clear hierarchy purpose
9. **Button rainbow** — every button is a different color
10. **Dashboard syndrome** — dashboard layout when a simpler interface would do
11. **Modal mania** — modals for interactions that should be inline

For each detected: describe the issue, recommend the fix, add to plan.

### Pass 4: 7 Litmus Checks

Quick yes/no checks that catch common design failures:

1. **Squint test** — Squint at the layout. Can you still identify the primary action?
2. **3-second rule** — Can a new user understand what this does in 3 seconds?
3. **Thumb test** — Can the primary action be reached with one thumb on mobile?
4. **Grandma test** — Would a non-technical user understand the labels?
5. **Bad day test** — Would this still work on a slow 3G connection with a cracked screen?
6. **Grumpy test** — If the user is already annoyed, does this design make it worse?
7. **Copy test** — If you remove all the copy, does the layout still make sense?

### Pass 5: Fix Toward 10

For each dimension scoring <8:
1. Write specific design recommendations (not "improve spacing" but "increase gap between cards from 12px to 24px")
2. Prioritize by impact: which fixes move the most dimensions toward 10?
3. Add these to the plan as design decisions with rationale

### Pass 6: "NOT in Scope" + "What Already Exists"

**NOT in Scope:** Explicitly document what design work is NOT being done:
```
### NOT in Scope
1. [Design item] — [Why excluded] — [When to reconsider]
```

**What Already Exists:** Check for existing design system tokens, components, and patterns that should be reused:
- DESIGN.md or design system file
- Existing CSS custom properties / Tailwind config
- Component library patterns
- Brand guidelines

### Pass 7: Completion Summary

Produce the final output with all scores and decisions.

## Output Format

```
## Design Review

### Dimension Scores
| Dimension | Score | Gap to 10 | Priority Fix | Hard Rule Status |
|-----------|-------|-----------|-------------|-----------------|
| Visual Hierarchy | 6 | Need clear CTA hierarchy | Add dominant CTA with visual weight | VIOLATION (fix) |
| Typography | 8 | Minor scale adjustments | Refine heading sizes | PASS |
| ... | ... | ... | ... | ... |

### AI Slop Detections
1. [Pattern] → [Location] → [Fix]

### Litmus Check Results
1. Squint test: PASS/FAIL — [notes]
2. 3-second rule: PASS/FAIL — [notes]
...

### Critical Design Decisions (add to plan)
1. [Decision] — [Rationale] — [Impact on score: X → Y]

### NOT in Scope
1. [Item] — [Why excluded] — [When to reconsider]

### What Already Exists
1. [Existing design element] → [How to reuse]

### Overall Assessment
- Average score: X/10
- Dimensions below 8: [count]
- Hard rule violations: [count]
- AI slop detections: [count]
- Litmus failures: [count]
```

## UX Principles Reference

- **Three Laws of Usability**: Don't make me think; It doesn't matter how many times I click as long as each click is a mindless choice; Get rid of half the words, then get rid of half of what's left
- **Scanning behavior**: Users scan in F-pattern, put important things at scan points
- **Billboard design**: Users glance, don't read — design for 3-second comprehension
- **Navigation wayfinding**: Users always need to know where they are, where they came from, where they can go
- **Goodwill reservoir**: Every frustration depletes goodwill; every delight restores it

## Important Rules

- **The gap method is mandatory.** Don't just rate — explain what a 10 looks like.
- **Hard rule violations are auto-fixed.** They're not taste decisions.
- **AI slop detection is not optional.** AI-generated designs have known failure modes.
- **"NOT in scope" must be explicit.** If something could reasonably be expected but isn't being designed, say so.
- **Specific recommendations only.** "Improve spacing" is not a recommendation. "Increase gap from 12px to 24px" is.
