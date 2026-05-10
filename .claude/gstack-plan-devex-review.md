# /plan-devex-review — Developer Experience Plan Review (Comate Adapted)

> DX-mode plan review: developer personas, TTHW benchmarks, magical moments, friction point triage. Before implementation. For live DX audits, use /devex-review.

## Three Modes

| Mode | When to use | Behavior |
|------|------------|----------|
| DX EXPANSION | "Make the DX amazing" | Dream big, no constraint on DX scope. Competitive advantage through developer love. |
| DX POLISH | Default | Focus on smoothing friction in current design. Bulletproof every touchpoint. |
| DX TRIAGE | "Just fix the worst" | Only address critical DX blockers. Ship the minimum acceptable DX. |

## 7 DX First Principles

1. **Zero friction at T0** — The first 5 minutes determine if a developer stays. If they can't succeed in 5 minutes, most won't try again.
2. **Incremental steps** — Each step should produce a visible result. No "configure 15 things then see output."
3. **Learn by doing** — Don't explain, let them experience. Code samples > documentation > theory.
4. **Errors teach** — Error messages should guide, not scold. "Expected X, got Y. Try: Z."
5. **Convention over configuration** — Sensible defaults, opt-in complexity. The happy path should be zero-config.
6. **Progressive power** — Easy things easy, hard things possible. Never make easy things hard to enable hard things.
7. **Respect for time** — Wait time is the enemy. Every second of loading/installing/building is a developer you might lose.

## 8 DX Characteristics

| # | Characteristic | Gold standard | Quick check |
|---|---------------|---------------|-------------|
| 1 | Usable | Stripe API | Can a developer complete their first task in <5 min? |
| 2 | Credible | Tailwind docs | Does the documentation match reality? |
| 3 | Findable | MDN | Can developers discover features without knowing they exist? |
| 4 | Useful | Vercel CLI | Does it solve a real pain point? |
| 5 | Valuable | GitHub Actions | Does the time saved exceed the time invested? |
| 6 | Accessible | Next.js starters | Can beginners succeed as easily as experts? |
| 7 | Desirable | Linear | Does using it feel good? |
| 8 | Resilient | AWS SDK | Does it handle errors gracefully without losing work? |

## TTHW Benchmarks

| Rating | Time to Hello World | Description |
|--------|-------------------|-------------|
| Champion | < 2 minutes | Install → run → see result. Zero config. |
| Competitive | 2-5 minutes | Install → minimal config → run → see result. |
| Needs Work | 5-10 minutes | Install → configure → troubleshoot → run. |
| Red Flag | > 10 minutes | Install → configure → debug → read docs → give up. |

## Review Process

### Step 1: Pre-review Audit

Read: plan file, README, docs, package.json, API docs, CHANGELOG, getting-started guide. Understand what the developer-facing surface is.

### Step 2: Developer Persona Traces

For each persona, trace their first 5 minutes:

**New developer** — first encounter, no prior knowledge
- How do they find the project?
- What's their first action?
- What do they see after that action?
- Can they succeed without reading docs?

**Evaluating developer** — comparing with alternatives, skeptical
- What differentiators are visible in <30 seconds?
- Can they see a live demo or example?
- How does the API compare to competitors?

**Migrating developer** — coming from a competitor, looking for parallels
- Is there a migration guide?
- Are concepts mapped from the old system?
- Can they keep their existing workflow?

**Power user** — already knows the basics, pushing limits
- Can they discover advanced features?
- Is there an escape hatch for when the abstraction leaks?
- Can they customize without forking?

### Step 3: Friction Point Identification

For each step in the developer journey, identify:

**BLOCKER** — Will stop them from proceeding. Must fix before launch.
- Missing installation instructions
- Broken quick-start example
- Required config not documented
- Authentication required but not explained

**Speed bump** — Will slow them down but not stop them. Should fix.
- Unclear error messages
- Missing type definitions
- Non-obvious default behavior
- Hidden configuration options

**Paper cut** — Annoying but not blocking. Nice to fix.
- Inconsistent naming
- Verbose output
- Missing code examples
- Suboptimal defaults

### Step 4: Magical Moments

Design 2-3 "delight" moments:
- What would make a developer say "wow, that's clever"?
- Where can we exceed expectations?
- What's the thing they'll tell their colleagues about?

Categories of magical moments:
- **Instant gratification** — see result immediately (e.g., `npx create` → running app)
- **Smart defaults** — it just works without configuration
- **Helpful errors** — error messages that solve the problem
- **Progressive disclosure** — power features appear when needed
- **Time travel** — undo/redo, rollback, instant recovery

### Step 5: Error Quality Audit

Trace 5 common error scenarios:
1. Invalid input → What does the developer see? Is the fix obvious?
2. Authentication failure → Is the recovery path clear?
3. Rate limiting → Is the retry strategy documented?
4. Network error → Is it handled gracefully?
5. Missing configuration → Is the error message actionable?

**Error quality score:**
- Good: Error message + cause + fix suggestion + link to docs
- OK: Error message + cause + fix suggestion
- Bad: Error message + cause
- Terrible: Stack trace or cryptic code only

### Step 6: Documentation Audit

| Aspect | Check | Gold standard |
|--------|-------|---------------|
| README | Does it get you running in <5 min? | Copy-paste install + run |
| Quick Start | Is there a minimal example? | Complete working example |
| API Reference | Are all endpoints documented with examples? | Every endpoint with request/response |
| Error Guide | Are common errors explained with fixes? | Troubleshooting section |
| Migration Guide | Is there a guide for version upgrades? | Breaking changes + migration steps |
| Contributing | Is the dev setup documented? | Clone → install → test |

### Step 7: TTHW Estimation

Walk through the exact steps a new developer would take:

1. Find the project
2. Read README
3. Install dependencies
4. Configure environment
5. Run the first command
6. See the first result

For each step: time estimate, decisions required, potential failure points, clarity rating.

### Step 8: DX Scorecard

```
## DX Scorecard

### TTHW
- Estimated time: <X minutes>
- Steps required: <N>
- Decisions required: <N>
- Potential failure points: <N>
- Rating: Champion/Competitive/Needs Work/Red Flag

### Persona Trace Results
| Persona | First 5 min result | Friction points | Magical moments |
|---------|-------------------|----------------|----------------|
| New dev | [Can/can't] install + run hello | [N blockers, M speed bumps] | [Moments] |
| Evaluator | [Can/can't] see value prop | [N speed bumps] | [Moments] |
| Migrator | [Can/can't] find equivalents | [N paper cuts] | [Moments] |
| Power user | [Can/can't] access advanced | [N speed bumps] | [Moments] |

### Characteristic Scores
| Characteristic | Score (0-10) | Gap to 10 |
|---------------|-------------|-----------|
| Usable | | |
| Credible | | |
| Findable | | |
| Useful | | |
| Valuable | | |
| Accessible | | |
| Desirable | | |
| Resilient | | |

### Friction Summary
1. [BLOCKER] <description> → <fix>
2. [SPEED BUMP] <description> → <fix>
3. [PAPER CUT] <description> → <fix>

### Magical Moments
1. <moment> → <implementation>

### Error Quality
1. <scenario> → <current quality: Good/OK/Bad/Terrible> → <improvement>

### Documentation Score: <0-10>
```

## Important Rules

- **TTHW is the north star metric.** Every decision should move TTHW toward Champion.
- **Persona traces are not optional.** You must trace through each persona's actual experience.
- **BLOCKER friction points must be fixed before launch.** No exceptions.
- **Magical moments differentiate good DX from great DX.** Don't skip them.
- **Error quality is a first-class concern.** Most developers' first impression is an error message.
