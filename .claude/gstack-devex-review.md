# /devex-review — Developer Experience Live Audit (Comate Adapted)

> DX audit: TTHW measured against the real flow, friction points, magical moments.

Note: Original gstack uses live browser testing. This adaptation works with code/doc analysis.

## Step 1: TTHW Measurement

Time to Hello World — trace the exact steps a new developer would take:

1. Find the project (GitHub/search)
2. Read README
3. Install dependencies
4. Configure environment
5. Run the first command
6. See the first result

For each step:
- Time estimate
- Number of decisions required
- Number of potential failure points
- Clarity of instructions

**Rating:**
| Time | Rating |
|------|--------|
| < 2 min | Champion |
| 2-5 min | Competitive |
| 5-10 min | Needs Work |
| > 10 min | Red Flag |

## Step 2: Documentation Audit

| Aspect | Check |
|--------|-------|
| README | Does it get you running in <5 min? |
| Quick Start | Is there a minimal example? |
| API Reference | Are all endpoints documented with examples? |
| Error Guide | Are common errors explained with fixes? |
| Migration Guide | Is there a guide for version upgrades? |
| Contributing | Is the dev setup documented? |

## Step 3: API Ergonomics

For each API endpoint:
- Does the URL follow consistent conventions?
- Are request/response shapes documented?
- Do error responses follow a consistent format?
- Are there sensible defaults (pagination, filtering)?
- Is the authentication flow clear?

## Step 4: Error Quality

Trace 5 common error scenarios:
1. Invalid input → What does the user see?
2. Authentication failure → Is the fix obvious?
3. Rate limiting → Is the retry strategy clear?
4. Network error → Is it handled gracefully?
5. Missing configuration → Is the error message actionable?

**Error quality score:**
- Good: Error message + cause + fix suggestion
- OK: Error message + cause
- Bad: Stack trace or cryptic code only

## Step 5: Friction Point Report

```
## DX Audit

### TTHW
- Steps: <N>
- Estimated time: <X> minutes
- Rating: <Champion/Competitive/Needs Work/Red Flag>

### Documentation Score: <0-10>
### API Ergonomics Score: <0-10>
### Error Quality Score: <0-10>

### Friction Points
1. [BLOCKER] <description> → <fix recommendation>
2. [SPEED BUMP] <description> → <fix recommendation>
3. [PAPER CUT] <description> → <fix recommendation>

### Magical Moments (opportunities)
1. <what would delight developers>
```

## Proactive Trigger Rules

Invoke this skill when:
- User asks about developer experience
- User says "is this easy to use for developers?"
- Building APIs, SDKs, or CLIs
