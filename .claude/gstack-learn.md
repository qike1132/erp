# /learn — Manage Project Learnings (Comate Adapted)

> Review, search, prune, and export what's been learned across sessions. Patterns, pitfalls, preferences, and architecture decisions.

## Commands

- `/learn` — Show 20 most recent learnings
- `/learn search <query>` — Search learnings by keyword
- `/learn prune` — Remove stale/contradictory learnings
- `/learn export` — Format as markdown for CLAUDE.md
- `/learn stats` — Show learning statistics
- `/learn add` — Manually add a learning

## Learning Types

| Type | Description | Example |
|------|-------------|---------|
| Pattern | Recurring code pattern or convention | "Repository pattern for data access" |
| Pitfall | Known issue, gotcha, or failure mode | "FastAPI async generator DI breaks" |
| Preference | User/team preference or convention | "CamelCase in API responses" |
| Architecture | Structural decision about the system | "/api/v1/ prefix for all endpoints" |

Each learning has:
- **Key** — short identifier (e.g., "auth-strategy")
- **Insight** — the learning itself (1-3 sentences)
- **Confidence** — HIGH / MEDIUM / LOW
- **Source** — AUTO (discovered during work) / MANUAL (user-specified)
- **Related files** — optional file paths
- **Verified date** — when it was last confirmed true

## Show Recent (default)

Display 20 most recent learnings grouped by type:

```
## Recent Learnings

### Patterns (8)
1. [HIGH] Repository pattern for data access — verified 2026-05-08
   Key: data-access-pattern
   Insight: All database access goes through repository classes in src/repositories/
   Files: src/repositories/*.ts

2. [MED] Error responses follow RFC 7807 format — verified 2026-05-07
   Key: error-format
   Insight: All API errors use { type, title, status, detail } structure

### Pitfalls (3)
1. [HIGH] FastAPI dependency injection breaks with async generators — verified 2026-05-09
   Key: fastapi-async-di
   Insight: Using async generators for DI cleanup causes connection leaks. Use try/finally instead.

### Preferences (4)
1. [MED] User prefers TypeScript-style camelCase in APIs — verified 2026-05-06
   Key: api-naming
   Insight: API responses use camelCase despite Python backend using snake_case

### Architecture (5)
1. [HIGH] Frontend communicates with backend via /api/v1/ prefix — verified 2026-05-10
   Key: api-prefix
   Insight: All backend endpoints are under /api/v1/, proxied through nginx
```

## Search

Search by keyword across all learning types. Show matches with relevance:

```
## Search Results: "authentication"

1. [HIGH] auth-strategy — JWT with HS256 for API auth — verified 2026-05-08
2. [MED] api-prefix — All backend endpoints under /api/v1/ — verified 2026-05-10
3. [HIGH] fastapi-async-di — DI cleanup issue — verified 2026-05-09
```

Search across: key, insight, related files, type.

## Prune

Check for:

**Stale learnings:**
- Referenced files no longer exist
- Patterns contradicted by current code
- Architecture decisions that have been reversed
- Learnings older than 90 days with no verification

**Contradictory learnings:**
- Same key with different insights
- Two patterns that can't both be true

For each questionable entry, present to user:
```
⚠️ Potentially stale learning:
Key: auth-strategy
Insight: Using JWT with HS256
Verified: 2026-05-08 (3 days ago)
Reason: src/middleware/auth.ts now uses RS256

Options: [R]emove / [U]pdate / [K]eep / [S]kip
```

## Export

Format as markdown sections for adding to project docs:

```markdown
## Project Learnings

### Patterns
- Repository pattern for data access (HIGH confidence) — src/repositories/
- Error responses follow RFC 7807 (MEDIUM confidence)

### Pitfalls
- FastAPI async generator DI issue (HIGH confidence)
- N+1 queries in order listing endpoint (HIGH confidence) — src/api/orders.ts:45

### Preferences
- CamelCase in API responses (MEDIUM confidence)
- Prefer explicit over clever code (HIGH confidence)

### Architecture
- /api/v1/ prefix for all backend endpoints (HIGH confidence)
- PostgreSQL with JSONB for flexible schemas (HIGH confidence)
```

## Stats

```
## Learning Stats

Total: 47 entries
By type: Patterns(18), Pitfalls(9), Preferences(7), Architecture(13)
By confidence: HIGH(28), MEDIUM(14), LOW(5)
By source: AUTO(32), MANUAL(15)
Average age: 12 days
Oldest unverified: 45 days (consider pruning)
Last verified: 2026-05-10
```

## Add

Gather via questions:
1. **Type:** Pattern / Pitfall / Preference / Architecture
2. **Key:** short identifier (snake_case)
3. **Insight:** the learning itself (1-3 sentences)
4. **Confidence:** HIGH / MEDIUM / LOW
5. **Related files** (optional)

Save to `.gstack/learnings.jsonl` in append-only format:
```json
{"key":"auth-strategy","type":"pattern","insight":"JWT with HS256 for API auth","confidence":"HIGH","source":"manual","verified":"2026-05-10","files":["src/middleware/auth.ts"]}
```

## Important Rules

- **Learnings are append-only.** Never overwrite — add new entries and prune old ones explicitly.
- **Verification dates matter.** A learning verified today is more trustworthy than one verified 3 months ago.
- **Prune aggressively.** Stale learnings are worse than no learnings — they cause incorrect assumptions.
- **Include file references when possible.** A learning with a file path is actionable; one without is theoretical.
- **Confidence is earned.** Default to MEDIUM for new learnings. Promote to HIGH after 2+ verifications.
