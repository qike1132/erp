# /devex-review — Developer Experience Live Audit (Comate Adapted)

> DX audit with measured TTHW, friction points, and magical moments. The "boomerang comparison" compares plan-mode DX review scores against live reality. For plan-mode DX review, use /plan-devex-review.

Note: Original gstack uses live browser testing. This adaptation works with code/doc analysis + manual verification.

## Step 1: TTHW Measurement

Time to Hello World — trace the EXACT steps a new developer would take:

1. Find the project (GitHub, search, referral)
2. Read README (or skip it?)
3. Install dependencies
4. Configure environment
5. Run the first command
6. See the first result

For each step, document:
- **Time estimate** (realistic, not optimistic)
- **Decisions required** (each decision is a friction point)
- **Potential failure points** (anything that could go wrong)
- **Clarity rating** (1-5: 1 = no clue, 5 = crystal clear)

**TTHW Rating:**
| Time | Rating | Implication |
|------|--------|-------------|
| < 2 min | Champion | Zero-config, instant gratification |
| 2-5 min | Competitive | Minimal config, clear instructions |
| 5-10 min | Needs Work | Multiple config steps, some troubleshooting |
| > 10 min | Red Flag | Developers will abandon before succeeding |

## Step 2: Documentation Audit

| Aspect | Check | Gold standard | Score (0-10) |
|--------|-------|---------------|-------------|
| README | Does it get you running in <5 min? | Copy-paste install + run command | |
| Quick Start | Is there a minimal example? | Complete, runnable code sample | |
| API Reference | Are all endpoints documented with examples? | Every endpoint with request/response examples | |
| Error Guide | Are common errors explained with fixes? | Troubleshooting section with solutions | |
| Migration Guide | Is there a guide for version upgrades? | Breaking changes + step-by-step migration | |
| Contributing | Is the dev setup documented? | Clone → install → test in <10 min | |

For each aspect: rate 0-10, note what's missing, note what's wrong.

## Step 3: API Ergonomics

For each API endpoint, evaluate:

- **URL conventions** — consistent naming, RESTful where appropriate
- **Request/response shapes** — documented, predictable, consistent
- **Error format** — consistent structure with actionable messages
- **Defaults** — sensible pagination, filtering, sorting defaults
- **Authentication** — clear flow, multiple methods if needed
- **Versioning** — clear strategy, backward compatibility
- **Rate limiting** — documented, headers included in responses

Score each: 0-10

## Step 4: Error Quality Audit

Trace 5 common error scenarios and evaluate the developer experience:

1. **Invalid input** → What does the developer see? Is the fix obvious?
2. **Authentication failure** → Is the recovery path clear?
3. **Rate limiting** → Is the retry strategy documented?
4. **Network error** → Is it handled gracefully?
5. **Missing configuration** → Is the error message actionable?

**Error quality score:**
- Good: Error message + cause + fix suggestion + link to docs
- OK: Error message + cause + fix suggestion
- Bad: Error message + cause
- Terrible: Stack trace or cryptic code only

For each error scenario: document current quality, recommend improvement, estimate fix effort.

## Step 5: Developer Persona Traces

For each persona, trace their first 5 minutes:

**New developer** — first encounter
- What's their first action?
- Where do they get stuck?
- How long until first success?

**Evaluating developer** — comparing alternatives
- What differentiators are visible in 30 seconds?
- Can they see a live demo?
- How does it compare to competitors?

**Migrating developer** — coming from a competitor
- Is there a migration guide?
- Are concepts mapped from the old system?
- How long until they're productive?

**Power user** — pushing limits
- Can they discover advanced features?
- Is there an escape hatch?
- How's the CLI/documentation for advanced use?

## Step 6: Friction Point Identification

For each step in the developer journey, identify:

**BLOCKER** — Will stop them from proceeding
- Missing installation instructions
- Broken quick-start example
- Required config not documented
- Authentication required but not explained
- Dependencies that fail to install

**Speed bump** — Will slow them down
- Unclear error messages
- Missing type definitions
- Non-obvious default behavior
- Hidden configuration options
- Verbose setup process

**Paper cut** — Annoying but not blocking
- Inconsistent naming
- Verbose output
- Missing code examples
- Suboptimal defaults
- No tab completion

## Step 7: Magical Moments

Identify opportunities for delight:
- **Instant gratification** — `npx create` → running app in seconds
- **Smart defaults** — it works without any configuration
- **Helpful errors** — error messages that solve the problem
- **Progressive disclosure** — power features appear when needed
- **Time travel** — undo/redo, rollback, instant recovery

For each: describe the moment, estimate implementation effort, estimate developer impact.

## Step 8: Boomerang Comparison

If a `/plan-devex-review` was done before implementation, compare plan vs. reality:

```
## Boomerang: Plan vs. Reality

| Metric | Plan predicted | Reality measured | Delta |
|--------|---------------|-----------------|-------|
| TTHW | 3 min | 8 min | +5 min ⚠️ |
| Documentation score | 8/10 | 6/10 | -2 |
| Error quality | Good | OK | -1 tier |
| Friction points | 3 | 7 | +4 ⚠️ |

### What we got right
1. [Where plan matched reality]

### What we got wrong
1. [Where plan was optimistic] → [Root cause]

### Unexpected issues
1. [Issues not predicted in plan] → [How to prevent next time]
```

## Output

```
## DX Audit

### TTHW
- Steps: <N>
- Estimated time: <X> minutes
- Rating: <Champion/Competitive/Needs Work/Red Flag>

### Documentation Score: <0-10>
### API Ergonomics Score: <0-10>
### Error Quality Score: <0-10>

### Persona Trace Results
| Persona | First 5 min result | Friction | Magical moments |
|---------|-------------------|----------|----------------|
| New dev | | | |
| Evaluator | | | |
| Migrator | | | |
| Power user | | | |

### Friction Points
1. [BLOCKER] <description> → <fix recommendation> → <effort>
2. [SPEED BUMP] <description> → <fix recommendation> → <effort>
3. [PAPER CUT] <description> → <fix recommendation> → <effort>

### Magical Moments (opportunities)
1. <moment> → <implementation> → <effort> → <impact>

### Boomerang (if plan review exists)
[Plan vs. reality comparison]
```

## Important Rules

- **TTHW is measured, not estimated.** Actually trace the steps, don't guess.
- **Error quality is a first-class concern.** Most developers' first experience is an error message.
- **BLOCKER friction points must be fixed.** No developer should be stuck on onboarding.
- **The boomerang comparison is valuable.** It tells you where your DX planning is inaccurate.
- **Persona traces are not optional.** Different developers have different needs.
