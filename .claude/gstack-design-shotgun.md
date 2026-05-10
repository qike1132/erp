# /design-shotgun — Design Explorer (Comate Adapted)

> Generate 4-6 AI mockup variants, compare, iterate, hand off to /design-html.

## Step 1: Define the Design Challenge

Ask the user:
- What page/component are we designing?
- Who are the users?
- What's the primary action?
- Any constraints (brand colors, existing components, responsive requirements)?

## Step 2: Generate Variants

Generate 4-6 distinct design variants. Each variant should explore a DIFFERENT design direction:

| Variant | Direction | Characteristics |
|---------|-----------|----------------|
| A | Minimal | Maximum whitespace, fewest elements, single-column |
| B | Data-dense | Dashboard-style, multi-column, information-rich |
| C | Conversational | Chat/wizard-based, step-by-step, guided |
| D | Visual-first | Hero images/illustrations, emotional, aspirational |
| E | Functional | Task-centric, keyboard-driven, power-user focused |
| F | Experimental | Unconventional layout, creative interaction pattern |

For each variant, produce:
- Layout description (ASCII wireframe or structural description)
- Key design decisions and rationale
- Strengths and trade-offs

## Step 3: Comparison Board

Present all variants side by side:
```
## Design Comparison

| Criterion | A (Minimal) | B (Data-dense) | C (Conversational) | D (Visual) | E (Functional) | F (Experimental) |
|-----------|------------|----------------|-------------------|------------|----------------|------------------|
| First impression | Clean | Overwhelming | Friendly | Beautiful | Efficient | Intriguing |
| Learning curve | Low | Medium | Low | Low | High | High |
| Information density | Low | High | Medium | Low | High | Medium |
| Mobile friendly | Yes | Hard | Yes | Medium | Hard | Varies |
| Build complexity | Low | High | Medium | Medium | High | High |
```

## Step 4: Collect Feedback

Ask the user:
- "Which direction resonates? Pick one, or combine elements from multiple."
- "What do you like about each?"
- "What would you change?"

## Step 5: Iterate

Refine the chosen direction with 2-3 iterations:
1. Incorporate feedback
2. Fill in details (responsive behavior, states, edge cases)
3. Validate against design principles

## Step 6: Hand Off

Once the user is satisfied with a direction:
- Document all design decisions
- If using `/design-html`, provide the spec for implementation
- If implementing manually, provide the design token values and layout structure

## Taste Memory

Note the user's preferences across sessions:
- Prefers minimal or data-dense?
- Values efficiency over beauty or vice versa?
- Mobile-first or desktop-first?
- Familiar design patterns or novel ones?

## Proactive Trigger Rules

Invoke this skill when:
- User says "show me options" for a design
- User is unsure about design direction
- User wants to explore multiple approaches before committing
