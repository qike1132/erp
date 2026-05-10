# /design-review — Live Site Visual Audit (Comate Adapted)

> Visual audit + fix loop. Rate each dimension, find issues, fix with atomic commits, re-verify. For plan-mode design review (before implementation), use /plan-design-review.

Note: The original gstack `/design-review` uses the browse daemon for live screenshots. This Comate adaptation works with source code analysis + file reading instead.

## The 11 Phases

### Phase 1: Scope the Review

Ask the user:
- Which pages/views to review?
- Any specific concerns?
- What severity threshold? (All issues, or only MEDIUM+?)
- Should we fix issues or just report?

### Phase 2: Code Scanning

Read all relevant source files for the pages being reviewed:
- HTML/JSX templates
- CSS/SCSS/Tailwind classes
- Component files
- Layout files
- Asset references

Look for common patterns and anti-patterns.

### Phase 3: Design Dimension Audit (10 Categories, ~80 Items)

Rate each dimension 0-10 using the gap method:

#### 1. Visual Hierarchy (~8 items)
- Can users identify the primary action in <1 second?
- Is there a clear visual weight order?
- Are CTAs visually dominant?
- Is there a clear scanning path?
- Do headings create entry points?
- Is the most important content above the fold?
- Are secondary actions visually de-emphasized?
- Is visual noise minimal?

#### 2. Spacing Consistency (~8 items)
- Is spacing on a 4/8px grid?
- Are gaps consistent between similar elements?
- Is padding consistent within similar components?
- Is there breathing room around CTAs?
- Are section separations clear?
- Is the overall density appropriate?
- Is line-height consistent?
- Are margins consistent?

#### 3. Color Usage (~8 items)
- Do colors follow a defined system?
- Are contrast ratios sufficient (4.5:1 text, 3:1 large text)?
- Are semantic colors used consistently?
- Is there a clear primary/secondary/neutral hierarchy?
- Do colors work in dark mode?
- Are there orphan colors (used once)?
- Do links have distinct styles?
- Is color the only indicator of meaning (it shouldn't be)?

#### 4. Typography (~8 items)
- Is there a clear type scale?
- Are font sizes consistent?
- Is line-height appropriate (1.5 body, 1.2 headings)?
- Is the font stack defined?
- Are there too many font sizes (>6)?
- Is body text at least 16px?
- Is there a clear heading hierarchy?
- Are font weights used consistently?

#### 5. Interactive States (~8 items)
- Do all buttons have hover, focus, active, disabled states?
- Do all inputs have focus states?
- Are focus indicators visible (3px+ outline)?
- Do links have hover and visited states?
- Are transitions smooth (150-250ms)?
- Are there loading states for async operations?
- Are disabled elements clearly distinguishable?
- Is cursor appropriate for each element?

#### 6. Responsive (~8 items)
- Does it work at every breakpoint?
- Is there horizontal overflow on mobile?
- Do touch targets meet 44px minimum?
- Does navigation collapse on mobile?
- Do images scale properly?
- Does text remain readable at all sizes?
- Are there layout shifts at breakpoints?
- Is content hidden or reorganized (not just scaled)?

#### 7. Error States (~8 items)
- Do forms show validation errors?
- Are error messages helpful (state problem + solution)?
- Are errors inline (near the field)?
- Is there global error handling?
- Are 404/500 pages designed?
- Do errors persist until dismissed or fixed?
- Are error states accessible?
- Can users recover from errors?

#### 8. Empty States (~8 items)
- Is there content for no-data scenarios?
- Do empty states guide the user to action?
- Are there illustrations or visual interest?
- Is the empty state visually distinct from an error?
- Do all lists/tables have empty states?
- Do search results have empty states?
- Is the tone appropriate (not condescending)?
- Is there a clear next action?

#### 9. Loading States (~8 items)
- Are there spinners/skeletons for async content?
- Is progress visible for long operations?
- Are skeleton screens used (not just spinners)?
- Is optimistic UI used where appropriate?
- Do loading states match the layout (no layout shift)?
- Is there a timeout indicator?
- Are loading states accessible?
- Is there feedback during the wait?

#### 10. Accessibility (~8 items)
- ARIA labels on interactive elements?
- Keyboard navigable (tab order, focus management)?
- Screen reader friendly (landmarks, headings)?
- Alt text on all images?
- Skip-to-content link?
- Focus trap in modals?
- Color not the only indicator of meaning?
- Works with prefers-reduced-motion?

### Phase 4: Issue Triage

For each issue found, classify:
- **CRITICAL** — broken functionality, inaccessible, data loss risk
- **HIGH** — ugly, confusing, violates design principles
- **MEDIUM** — inconsistent, slightly off-pattern
- **LOW** — nitpick, personal preference

For each issue:
- **Location**: specific file:line
- **Description**: what's wrong and why
- **Fix**: concrete CSS/HTML change (not "improve X" but "change padding from 8px to 16px")
- **Effort**: trivial / small / medium / large

### Phase 5: Fix Loop

For each issue at or above the severity threshold:

1. **Fix** with a targeted edit (surgical, not refactor)
2. **Describe** what was changed (commit message quality)
3. **Verify** the fix didn't break anything else
4. **Commit** atomically: `fix(ui): <what was fixed>`

**Goodwill reservoir**: Every UI has a finite goodwill budget. Each frustration depletes it; each delight restores it. Prioritize fixes that prevent depletion over those that add delight.

**Self-regulation risk heuristic**: If you've made 10+ fixes without the user checking, pause and present progress. You may be drifting from their intent.

### Phase 6: AI Slop Detection

Check for AI-generated design anti-patterns:
1. Gradient soup — gradients without semantic purpose
2. Card-itis — everything in cards with rounded corners and shadow
3. Purple haze — defaulting to purple without brand justification
4. Hero inflation — massive hero sections with no content
5. Icon salad — icons that don't add information
6. Animation bloat — animating everything
7. Whitespace desert — too much padding creating disconnect
8. Font overload — 3+ font families
9. Button rainbow — every button a different color
10. Dashboard syndrome — dashboard layout for simple content

### Phase 7: Before/After Summary

```
## Design Review Summary

### Dimension Scores
| Dimension | Before | After | Change |
|-----------|--------|-------|--------|
| Visual Hierarchy | 5 | 8 | +3 |
| Spacing Consistency | 4 | 7 | +3 |
| Color Usage | 6 | 8 | +2 |
| Typography | 7 | 8 | +1 |
| Interactive States | 3 | 7 | +4 |
| Responsive | 6 | 7 | +1 |
| Error States | 4 | 7 | +3 |
| Empty States | 2 | 6 | +4 |
| Loading States | 3 | 7 | +4 |
| Accessibility | 5 | 8 | +3 |

### Issues Found
- CRITICAL: 0 (0 fixed)
- HIGH: 3 (3 fixed)
- MEDIUM: 5 (2 fixed, 3 deferred)
- LOW: 8 (0 fixed, 8 deferred)

### AI Slop Detections
1. [Pattern] → [Location] → [Status: fixed/deferred]

### Commits
1. fix(ui): add focus-visible outlines to all buttons
2. fix(ui): normalize spacing to 4px grid
3. fix(ui): add empty state for order list

### Deferred Issues
1. [MEDIUM] <description> — <why deferred>
2. [LOW] <description> — <why deferred>
```

## Important Rules

- **The fix loop is the core value.** A design review that only reports issues is half-done.
- **Atomic commits.** Each fix is its own commit. Never bundle unrelated fixes.
- **Surgical edits.** Fix only the issue, don't refactor surrounding code.
- **Self-regulate.** If you've made 10+ fixes, pause and show progress.
- **Goodwill reservoir.** Prioritize preventing frustration over adding delight.
- **Specific fixes only.** "Improve spacing" is not a fix. "Change padding from 8px to 24px on .card-body" is.
