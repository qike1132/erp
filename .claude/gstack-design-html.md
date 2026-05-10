# /design-html — Design Engineer (Comate Adapted)

> Turn a mockup/direction into production HTML/CSS. Works with approved mockups from /design-shotgun, CEO plans from /plan-ceo-review, design review context from /plan-design-review, or from scratch with a user description. Text actually reflows, heights are computed, layouts are dynamic.

## Step 1: Detect Context

1. **Is there a `/design-shotgun` output?** — use the chosen variant's spec
2. **Is there a `/design-consultation` output (DESIGN.md)?** — use those tokens and patterns
3. **Is there a `/plan-design-review` output?** — use the design decisions
4. **What framework does the project use?** — React/Vue/Svelte/vanilla
5. **What CSS system?** — Tailwind/CSS Modules/vanilla CSS/styled-components
6. **Any existing design tokens or component library?** — reuse, don't reinvent

If none of these exist, ask the user what they want built and propose a design direction before implementing.

## Step 2: Design Type Detection

| Design type | Characteristics | Approach | Smart routing |
|-------------|---------------|----------|---------------|
| Landing page | Hero + CTA + features + social proof | Single file, mobile-first, scroll animations | Emphasis on typography, hero impact, conversion |
| Dashboard | Data + charts + tables + sidebar | Grid layout, responsive sidebar, data-dense | Emphasis on information density, scanability |
| Form | Input + validation + submit + progress | Accessible, error states, progressive disclosure | Emphasis on validation UX, label clarity |
| Documentation | Nav + content + search + TOC | Readable typography, syntax highlighting, scroll | Emphasis on readability, navigation, findability |
| Marketing | Story + visuals + conversion + testimonials | Emotional, scroll-driven, large imagery | Emphasis on visual impact, narrative flow |
| Settings | Tabs/sections + toggles + saves | Clear grouping, confirmation for destructive actions | Emphasis on clarity, safety, organization |

## Step 3: Implementation Principles

### Layout
- **CSS Grid for page layout** — define rows and columns at the page level
- **Flexbox for component layout** — align items within a component
- **Mobile-first** — design for 320px, expand with `min-width` media queries
- **CSS custom properties for all design tokens** — no hardcoded values
- **Avoid fixed pixel widths** — use max-width + percentage for fluid layouts
- **Container queries where supported** — component-level responsiveness

### Typography
- System font stack or project's chosen font
- **Modular scale:** 0.75rem → 0.875rem → 1rem → 1.25rem → 1.5rem → 2rem
- **Line-height:** 1.5 for body, 1.2 for headings
- **Measure (line-length):** 45-75 characters for body text
- **Font pairing:** 1 sans-serif + 1 monospace maximum

### Interactions
- **Hover states** on all interactive elements (subtle but visible)
- **Focus-visible outlines** (3px solid, 2px offset, primary color) — NEVER outline:none without replacement
- **Smooth transitions** (150-250ms ease) for state changes
- **Active states** — press feedback (slight scale or color shift)
- **Disabled states** — reduced opacity, cursor:not-allowed
- **prefers-reduced-motion: reduce** → disable ALL animations and transitions

### Responsive
```css
/* Mobile-first breakpoints */
/* Default: mobile (0-639px) */
@media (min-width: 640px) { /* sm */ }
@media (min-width: 768px) { /* md */ }
@media (min-width: 1024px) { /* lg */ }
@media (min-width: 1280px) { /* xl */ }
```

### Accessibility (mandatory)
- Semantic HTML elements (header, main, nav, section, article, footer)
- ARIA labels on interactive elements
- ARIA landmarks for page structure
- Role attributes where semantic HTML isn't enough
- Alt text on all images
- Keyboard navigable (tab order, focus management)
- Skip-to-content link
- Color contrast ≥ 4.5:1 for text
- Touch targets ≥ 44px × 44px
- No information conveyed by color alone

## Step 4: Build Process

1. **Create the HTML structure** with semantic elements
2. **Add CSS custom properties** for all design tokens (if not already in DESIGN.md)
3. **Implement the layout** (mobile-first, CSS Grid + Flexbox)
4. **Add typography and spacing** (using token references)
5. **Add interactive states** (hover, focus, active, disabled)
6. **Add responsive behavior** (breakpoints with meaningful layout changes)
7. **Add animations/transitions** (with prefers-reduced-motion fallback)
8. **Add dark theme** (if design includes it)
9. **Test accessibility** (contrast, keyboard nav, ARIA, screen reader)

## Step 5: Quality Checklist

- [ ] Works at 320px, 768px, 1024px, 1280px
- [ ] All interactive elements have hover, focus, active, disabled states
- [ ] Color contrast ≥ 4.5:1 for all text
- [ ] Touch targets ≥ 44px × 44px
- [ ] Works with `prefers-reduced-motion: reduce`
- [ ] Semantic HTML with proper ARIA labels
- [ ] No horizontal overflow on mobile
- [ ] Print stylesheet works (hide nav, simplify layout)
- [ ] Dark theme works (if applicable)
- [ ] All design tokens referenced as CSS custom properties
- [ ] No hardcoded colors, spacing, or font sizes
- [ ] Focus management works for modals and dialogs
- [ ] Skip-to-content link present

## Important Rules

- **Design tokens are non-negotiable.** No `color: #333` — use `var(--color-neutral-700)`.
- **Mobile-first is not optional.** Write mobile styles as default, add complexity at breakpoints.
- **All four interactive states are required.** Hover, focus, active, disabled — no exceptions.
- **Accessibility is built in.** If you can't make it accessible, choose a different design.
- **No placeholder content.** Use realistic text, not lorem ipsum. If you don't know the content, ask.
- **30KB overhead, zero deps.** The output should be self-contained CSS with no external dependencies.
