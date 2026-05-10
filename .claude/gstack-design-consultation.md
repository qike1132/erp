# /design-consultation — Design System Builder (Comate Adapted)

> Build a complete design system from scratch. Research the landscape, propose a system (aesthetic, typography, color, layout, spacing, motion), iterate, and save as DESIGN.md. For existing sites, use /plan-design-review to infer the system instead.

## Step 1: Product Understanding

Before proposing a design system, understand the product:

1. **What is the product?** — web app, mobile app, marketing site, developer tool
2. **Who are the users?** — technical, non-technical, children, professionals
3. **What's the emotional tone?** — serious/trustworthy, playful/fun, minimal/clean, bold/energetic
4. **What are the competitors?** — what do they look like? How should this be different?
5. **What are the constraints?** — brand colors, existing components, accessibility requirements

If the product has no clear identity, suggest `/office-hours` first.

## Step 2: Landscape Research

1. What design systems are relevant to this domain?
2. What are the common patterns for this type of application?
3. What would users expect visually?
4. What design systems do competitors use?
5. What design trends are current (but not trendy)?

## Step 3: Audit Existing Design

If the project already exists:

1. Scan the codebase for existing CSS/design files:
   - CSS/SCSS/Tailwind config files
   - Component libraries in use
   - Color/typography/spacing patterns
2. Identify inconsistencies: multiple shades of the same color, inconsistent spacing, mixed fonts
3. Note what works and what doesn't
4. Measure current design against design principles

## Step 4: Propose Design Tokens

### Colors
```css
/* Primary: brand identity */
--color-primary-50 through --color-primary-900
/* Secondary: supporting actions */
--color-secondary-50 through --color-secondary-900
/* Semantic: status and feedback */
--color-success / --color-warning / --color-error / --color-info
/* Neutral: text, backgrounds, borders */
--color-neutral-50 through --color-neutral-900
```

Rules:
- Primary palette must have 10 shades (50-900) for flexibility
- Semantic colors must pass contrast requirements against their backgrounds
- Every color must work in both light and dark themes
- No orphan colors — every color serves a purpose

### Typography
```css
/* Font families */
--font-sans: Inter, system-ui, sans-serif
--font-mono: JetBrains Mono, monospace
/* Font sizes (modular scale, ratio ~1.25) */
--text-xs: 0.75rem / --text-sm: 0.875rem / --text-base: 1rem
--text-lg: 1.125rem / --text-xl: 1.25rem / --text-2xl: 1.5rem
--text-3xl: 1.875rem / --text-4xl: 2.25rem
/* Font weights */
--font-normal: 400 / --font-medium: 500 / --font-semibold: 600 / --font-bold: 700
/* Line heights */
--leading-tight: 1.25 / --leading-normal: 1.5 / --leading-relaxed: 1.75
```

Rules:
- Maximum 2 font families (1 sans + 1 mono)
- Body text minimum 16px (1rem)
- Type scale must be consistent (modular scale ratio)
- Line height must increase as font size decreases

### Spacing
```css
/* 4px base unit */
--space-1: 0.25rem (4px) / --space-2: 0.5rem (8px) / --space-3: 0.75rem (12px)
--space-4: 1rem (16px) / --space-5: 1.25rem (20px) / --space-6: 1.5rem (24px)
--space-8: 2rem (32px) / --space-10: 2.5rem (40px) / --space-12: 3rem (48px)
--space-16: 4rem (64px) / --space-20: 5rem (80px)
```

Rules:
- All spacing values must be multiples of 4px
- Component internal padding: space-2 to space-4
- Component gaps: space-4 to space-8
- Section gaps: space-8 to space-16

### Shadows
```css
--shadow-sm: 0 1px 2px rgba(0,0,0,0.05)
--shadow-md: 0 4px 6px rgba(0,0,0,0.1)
--shadow-lg: 0 10px 15px rgba(0,0,0,0.1)
--shadow-xl: 0 20px 25px rgba(0,0,0,0.1)
```

### Transitions
```css
--transition-fast: 150ms ease
--transition-normal: 250ms ease
--transition-slow: 350ms ease
```

Rules:
- Interactive state changes: fast (150ms)
- Layout changes: normal (250ms)
- Complex animations: slow (350ms)
- Must respect `prefers-reduced-motion: reduce`

### Border Radius
```css
--radius-sm: 0.25rem (4px)
--radius-md: 0.5rem (8px)
--radius-lg: 0.75rem (12px)
--radius-full: 9999px
```

## Step 5: Component Patterns

### Button
```css
.btn { /* base: padding, font, border-radius, transition */ }
.btn:hover { /* subtle background shift */ }
.btn:focus-visible { /* 3px outline, 2px offset, primary color */ }
.btn:active { /* slight scale down (0.98) or darker bg */ }
.btn:disabled { /* reduced opacity, cursor not-allowed */ }
.btn-primary { /* primary bg, white text */ }
.btn-secondary { /* neutral bg, primary text, border */ }
.btn-danger { /* error bg, white text */ }
.btn-sm { /* reduced padding, smaller font */ }
.btn-lg { /* increased padding, larger font */ }
```

### Form Input
```css
.form-input { /* base: border, padding, font, border-radius */ }
.form-input:focus { /* border-color primary, box-shadow ring */ }
.form-input:invalid { /* border-color error */ }
.form-input:disabled { /* reduced opacity, bg change */ }
.form-label { /* font-weight medium, color neutral-700 */ }
.form-error { /* color error, font-size sm, margin-top space-1 */ }
.form-hint { /* color neutral-500, font-size sm */ }
```

### Card
```css
.card { /* bg white, shadow-sm, border-radius-lg, overflow hidden */ }
.card:hover { /* shadow-md, slight translateY(-1px) */ }
.card-header { /* padding space-4 to space-6, border-bottom */ }
.card-body { /* padding space-4 to space-6 */ }
.card-footer { /* padding space-4, border-top, bg neutral-50 */ }
```

### Additional Components (as needed)
- Badge, Alert, Modal, Toast, Dropdown, Tabs, Tooltip, Avatar, Skeleton

## Step 6: Dark Theme

```css
[data-theme="dark"] {
  /* Override all color tokens — swap neutral scale */
  --color-neutral-50: #1a1a2e;  /* dark bg */
  --color-neutral-100: #16213e;
  --color-neutral-900: #f0f0f0; /* light text */

  /* Reduce shadow intensity (shadows less visible on dark) */
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.3);
  --shadow-md: 0 4px 6px rgba(0,0,0,0.4);

  /* Adjust semantic colors for dark backgrounds */
  --color-success: /* brighter green */;
  --color-error: /* brighter red */;

  /* Adjust border colors */
  --border-default: /* lighter than dark bg */;
}
```

Rules:
- Dark theme must pass same contrast requirements as light
- Shadows need increased opacity in dark mode
- Never just invert colors — adjust each token intentionally
- Semantic colors may need hue shifts for dark backgrounds

## Step 7: Responsive Framework

Mobile-first breakpoints:
```css
/* Default: mobile (0-639px) */
@media (min-width: 640px) { /* sm */ }
@media (min-width: 768px) { /* md */ }
@media (min-width: 1024px) { /* lg */ }
@media (min-width: 1280px) { /* xl */ }
```

Rules:
- Default styles are mobile
- Use `min-width` media queries only
- Each breakpoint should show meaningful layout change, not just scaling
- Navigation must collapse to hamburger on mobile

## Step 8: Accessibility

- Color contrast ratio ≥ 4.5:1 for normal text, ≥ 3:1 for large text
- Touch targets ≥ 44px × 44px
- Focus-visible outlines on all interactive elements (3px solid, 2px offset)
- `prefers-reduced-motion: reduce` → disable all animations and transitions
- Semantic HTML with proper ARIA labels
- Focus trap in modals
- Skip-to-content link
- Form labels associated with inputs (not just placeholder text)

## Step 9: Generate Preview Pages

Create two preview files:
1. **Color palette page** — show all colors in both light and dark themes
2. **Typography page** — show all type scales, weights, and combinations

These serve as both documentation and verification.

## Output

Save as `DESIGN.md` in the project root with:
- All design tokens as CSS custom properties
- Component patterns with code examples
- Dark theme overrides
- Responsive breakpoint rules
- Accessibility requirements
- Usage guidelines (when to use which component, spacing rules, etc.)

## Important Rules

- **Design tokens are the source of truth.** No hardcoded values in components.
- **Maximum 2 font families.** More is visual noise.
- **All spacing on 4px grid.** No exceptions.
- **Dark theme is not optional.** Design for both from the start.
- **Accessibility is built in, not bolted on.** Contrast, focus states, ARIA, reduced motion.
- **Components must have all interactive states.** Hover, focus, active, disabled — all four.
