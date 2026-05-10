# /design-shotgun — Design Explorer (Comate Adapted)

> Generate 4-6 AI design variants, open a comparison board, collect structured feedback, and iterate. Standalone design exploration you can run anytime. Hands off to /design-html for implementation.

## Step 1: Context Gathering

Before generating variants, gather:

1. **What page/component are we designing?** — landing page, dashboard, form, settings, etc.
2. **Who are the users?** — personas, technical level, goals
3. **What's the primary action?** — the ONE thing this page must accomplish
4. **Any constraints?** — brand colors, existing components, responsive requirements
5. **What already exists?** — check for DESIGN.md, existing components, brand guidelines
6. **What's the emotional tone?** — serious, playful, minimal, bold

If a `/design-consultation` output exists (DESIGN.md), use those tokens and patterns.

## Step 2: Generate Variants

Generate 4-6 distinct design variants. Each variant should explore a DIFFERENT design direction:

| Variant | Direction | Characteristics | Best for |
|---------|-----------|----------------|----------|
| A | Minimal | Maximum whitespace, fewest elements, single-column, one CTA | Content-focused products, trust-building |
| B | Data-dense | Dashboard-style, multi-column, information-rich, progressive disclosure | Power users, B2B tools, analytics |
| C | Conversational | Chat/wizard-based, step-by-step, guided, friendly copy | Onboarding, complex workflows, non-technical users |
| D | Visual-first | Hero images/illustrations, emotional, aspirational, large type | Marketing, consumer products, brand-building |
| E | Functional | Task-centric, keyboard-driven, power-user focused, dense shortcuts | Developer tools, internal tools, expert users |
| F | Experimental | Unconventional layout, creative interaction pattern, unique | Differentiation, portfolio pieces, art-forward brands |

For each variant, produce:
- **Layout description** (structural description of the page sections)
- **Wireframe** (ASCII wireframe showing spatial arrangement)
- **Key design decisions** and rationale
- **Strengths** — what this direction excels at
- **Trade-offs** — what this direction sacrifices
- **Component mapping** — which existing components are reused, which are new

### Wireframe Format
```
┌─────────────────────────────────────┐
│ [Nav]  Logo    [Items]    [CTA]     │
├─────────────────────────────────────┤
│                                     │
│         [Hero: Headline]            │
│         [Subheadline]               │
│         [Primary CTA]               │
│                                     │
├──────────┬──────────┬───────────────┤
│ [Card 1] │ [Card 2] │ [Card 3]     │
│          │          │               │
└──────────┴──────────┴───────────────┘
```

## Step 3: Comparison Board

Present all variants side by side with structured comparison:

```
## Design Comparison

| Criterion | A (Minimal) | B (Data-dense) | C (Conversational) | D (Visual) | E (Functional) | F (Experimental) |
|-----------|------------|----------------|-------------------|------------|----------------|------------------|
| First impression | Clean | Overwhelming | Friendly | Beautiful | Efficient | Intriguing |
| Learning curve | Low | Medium | Low | Low | High | High |
| Information density | Low | High | Medium | Low | High | Medium |
| Mobile friendly | Yes | Hard | Yes | Medium | Hard | Varies |
| Build complexity | Low | High | Medium | Medium | High | High |
| Uniqueness | Low | Medium | Medium | Medium | Medium | High |
| Primary user fit | [rating] | [rating] | [rating] | [rating] | [rating] | [rating] |
```

## Step 4: Collect Structured Feedback

Ask the user:

1. **Direction preference** — "Which direction resonates? Pick one, or combine elements from multiple."
2. **Element preferences** — "What do you like about each?"
3. **Change requests** — "What would you change?"
4. **Dealbreakers** — "What would make a direction unacceptable?"
5. **Confidence** — "How confident are you in this direction? (1-5)"

If the user picks multiple directions, identify the common elements (the "core") and the variable elements (the "flavor"). Propose a hybrid that keeps the core and lets the user choose the flavor.

## Step 5: Iterate

Refine the chosen direction with 2-3 iterations:

**Iteration 1: Structure refinement**
- Incorporate feedback
- Adjust layout proportions
- Refine content hierarchy

**Iteration 2: Detail fill**
- Add responsive behavior (mobile/tablet/desktop)
- Add interactive states (hover, focus, active, disabled)
- Add edge cases (empty states, error states, loading states)

**Iteration 3: Validation**
- Validate against design principles (from /design-consultation or /plan-design-review)
- Check accessibility (contrast, touch targets, keyboard nav)
- Check consistency with existing design system

## Step 6: Document & Hand Off

Once the user is satisfied with a direction:

1. **Document all design decisions:**
   - Layout structure with measurements
   - Component choices and variations
   - Responsive breakpoints and behavior
   - Interactive states
   - Content guidelines (character limits, image specs)

2. **Map to design tokens** (if DESIGN.md exists):
   - Which tokens are used where
   - Any new tokens needed
   - Any token value overrides

3. **Hand off options:**
   - If using `/design-html`: provide the complete spec for implementation
   - If implementing manually: provide design token values, layout structure, and component specs
   - If using a framework: note which components map to which framework components

## Taste Memory

Note the user's preferences across sessions:
- Prefers minimal or data-dense?
- Values efficiency over beauty or vice versa?
- Mobile-first or desktop-first?
- Familiar design patterns or novel ones?
- High information density or breathing room?

Save these observations for future /design-shotgun runs.

## Important Rules

- **Variants must be genuinely different.** Two variants that differ only in button color are not different directions.
- **Wireframes are structural, not visual.** Focus on layout and hierarchy, not colors and fonts.
- **Every variant must solve the primary action.** A beautiful design that doesn't accomplish the goal is a bad design.
- **The comparison board must be honest.** Don't bias toward your preferred variant.
- **Iteration is expected.** The first variant chosen rarely survives unchanged.
