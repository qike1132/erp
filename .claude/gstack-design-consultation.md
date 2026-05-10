# /design-consultation — Design System Builder (Comate Adapted)

> Build a complete design system from scratch. Research, propose, iterate.

## Step 1: Audit Existing Design

1. Scan the codebase for existing CSS/design files:
   - CSS/SCSS/Tailwind config files
   - Component libraries in use
   - Color/typography/spacing patterns
2. Identify inconsistencies: multiple shades of the same color, inconsistent spacing, mixed fonts
3. Note what works and what doesn't

## Step 2: Research the Landscape

1. What design systems are relevant to this domain?
2. What are the common patterns for this type of application?
3. What would users expect visually?

## Step 3: Propose Design Tokens

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

### Typography
```css
/* Font families */
--font-sans: Inter, system-ui, sans-serif
--font-mono: JetBrains Mono, monospace
/* Font sizes (4px base unit) */
--text-xs: 0.75rem / --text-sm: 0.875rem / --text-base: 1rem / --text-lg: 1.125rem / --text-xl: 1.25rem / --text-2xl: 1.5rem
/* Font weights */
--font-normal: 400 / --font-medium: 500 / --font-semibold: 600 / --font-bold: 700
/* Line heights */
--leading-tight: 1.25 / --leading-normal: 1.5 / --leading-relaxed: 1.75
```

### Spacing
```css
/* 4px base unit */
--space-1: 0.25rem / --space-2: 0.5rem / --space-3: 0.75rem / --space-4: 1rem
--space-5: 1.25rem / --space-6: 1.5rem / --space-8: 2rem / --space-10: 2.5rem
--space-12: 3rem / --space-16: 4rem / --space-20: 5rem
```

### Shadows
```css
--shadow-sm: 0 1px 2px rgba(0,0,0,0.05)
--shadow-md: 0 4px 6px rgba(0,0,0,0.1)
--shadow-lg: 0 10px 15px rgba(0,0,0,0.1)
```

### Transitions
```css
--transition-fast: 150ms ease
--transition-normal: 250ms ease
--transition-slow: 350ms ease
```

## Step 4: Component Patterns

### Button
```css
.btn { /* base styles */ }
.btn:hover { /* hover state */ }
.btn:focus-visible { /* focus ring */ }
.btn:disabled { /* disabled state */ }
.btn-primary { /* primary variant */ }
.btn-secondary { /* secondary variant */ }
.btn-danger { /* destructive variant */ }
```

### Form Input
```css
.form-input { /* base styles */ }
.form-input:focus { /* focus ring */ }
.form-input:invalid { /* validation state */ }
.form-input:disabled { /* disabled state */ }
.form-label { /* label styles */ }
.form-error { /* error message */ }
```

### Card
```css
.card { /* base styles with shadow */ }
.card:hover { /* hover elevation */ }
.card-header { /* header section */ }
.card-body { /* content section */ }
.card-footer { /* action section */ }
```

## Step 5: Dark Theme

```css
[data-theme="dark"] {
  /* Override all color tokens */
  --color-neutral-50: /* dark bg */;
  --color-neutral-900: /* light text */;
  /* Reduce shadow intensity */
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.3);
}
```

## Step 6: Responsive Framework

Mobile-first breakpoints:
```css
/* Default: mobile */
@media (min-width: 640px) { /* sm */ }
@media (min-width: 768px) { /* md */ }
@media (min-width: 1024px) { /* lg */ }
@media (min-width: 1280px) { /* xl */ }
```

## Step 7: Accessibility

- Color contrast ratio ≥ 4.5:1 for normal text, ≥ 3:1 for large text
- Touch targets ≥ 44px
- Focus-visible outlines on all interactive elements
- `prefers-reduced-motion` support
- Semantic HTML with proper ARIA labels

## Output

Save as `DESIGN.md` in the project root with all tokens, patterns, and usage guidelines.

## Proactive Trigger Rules

Invoke this skill when:
- User asks to create or improve a design system
- User mentions "design tokens", "CSS variables", "component library"
- User wants dark mode or responsive design
