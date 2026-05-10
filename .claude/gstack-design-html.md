# /design-html — Design Engineer (Comate Adapted)

> Turn a mockup/direction into production HTML/CSS that actually works.

## Step 1: Detect Context

1. Is there a `/design-shotgun` or `/design-consultation` output to work from?
2. What framework does the project use? (React/Vue/Svelte/vanilla)
3. What CSS system? (Tailwind/CSS Modules/vanilla CSS)
4. Any existing design tokens or component library?

## Step 2: Design Type Detection

| Design type | Characteristics | Approach |
|-------------|---------------|----------|
| Landing page | Hero + CTA + features | Single file, mobile-first, animations |
| Dashboard | Data + charts + tables | Grid layout, responsive sidebar |
| Form | Input + validation + submit | Accessible, error states, progressive disclosure |
| Documentation | Nav + content + search | Readable typography, syntax highlighting |
| Marketing | Story + visuals + conversion | Emotional, scroll-driven, parallax |

## Step 3: Implementation Principles

### Layout
- CSS Grid for page layout, Flexbox for component layout
- Mobile-first: design for 320px, expand with media queries
- Use CSS custom properties for all design tokens
- Avoid fixed pixel widths; use max-width + percentage

### Typography
- System font stack or project's chosen font
- Modular scale: 0.75rem → 0.875rem → 1rem → 1.25rem → 1.5rem → 2rem
- Line-height: 1.5 for body, 1.2 for headings

### Interactions
- Hover states on all interactive elements
- Focus-visible outlines (3px solid, 2px offset)
- Smooth transitions (150-250ms ease)
- prefers-reduced-motion: reduce → disable all animations

### Responsive
```css
/* Mobile-first breakpoints */
@media (min-width: 640px) { /* sm */ }
@media (min-width: 768px) { /* md */ }
@media (min-width: 1024px) { /* lg */ }
@media (min-width: 1280px) { /* xl */ }
```

## Step 4: Build

1. Create the HTML structure with semantic elements
2. Add CSS custom properties for all design tokens
3. Implement the layout (mobile-first)
4. Add typography and spacing
5. Add interactive states (hover, focus, active, disabled)
6. Add responsive behavior
7. Add animations/transitions
8. Test accessibility (contrast, keyboard nav, ARIA)

## Step 5: Quality Check

- [ ] Works at 320px, 768px, 1024px, 1280px
- [ ] All interactive elements have focus states
- [ ] Color contrast ≥ 4.5:1 for text
- [ ] Touch targets ≥ 44px
- [ ] Works with prefers-reduced-motion
- [ ] Semantic HTML with proper ARIA
- [ ] No horizontal overflow on mobile
- [ ] Print stylesheet works

## Proactive Trigger Rules

Invoke this skill when:
- User wants to turn a design/mockup into working HTML
- User says "implement this design"
- User needs production-quality front-end code
