# /learn — Manage Project Learnings (Comate Adapted)

> Review, search, prune, and export what's been learned across sessions.

## Commands

- `/learn` — Show 20 most recent learnings
- `/learn search <query>` — Search learnings by keyword
- `/learn prune` — Remove stale/contradictory learnings
- `/learn export` — Format as markdown for CLAUDE.md
- `/learn stats` — Show learning statistics
- `/learn add` — Manually add a learning

## Show Recent (default)

Display 20 most recent learnings grouped by type:

```
## Recent Learnings

### Patterns (8)
1. [HIGH] This project uses repository pattern for data access — verified 2026-05-08
2. [MED] Error responses follow RFC 7807 format — verified 2026-05-07

### Pitfalls (3)
1. [HIGH] FastAPI dependency injection breaks with async generators — verified 2026-05-09

### Preferences (4)
1. [MED] User prefers TypeScript-style camelCase in APIs — verified 2026-05-06

### Architecture (5)
1. [HIGH] Frontend communicates with backend via /api/v1/ prefix — verified 2026-05-10
```

## Search

Search by keyword across all learning types. Show matches with relevance.

## Prune

Check for:
- **Stale learnings**: referenced files no longer exist, patterns contradicted by current code
- **Contradictory learnings**: same key with different insights

For each questionable entry, present to user:
- "This learning references `src/old-module.ts` which no longer exists. Remove or update?"

## Export

Format as markdown sections for adding to project docs:

```markdown
## Project Learnings

### Patterns
- Repository pattern for data access (HIGH confidence)

### Pitfalls
- FastAPI async generator dependency injection issue (HIGH confidence)

### Preferences
- CamelCase in API responses (MEDIUM confidence)

### Architecture
- /api/v1/ prefix for all backend endpoints (HIGH confidence)
```

## Stats

```
## Learning Stats
Total: 47 entries
By type: Patterns(18), Pitfalls(9), Preferences(7), Architecture(13)
By source: Auto(32), Manual(15)
Average confidence: 0.78
```

## Add

Gather via questions:
1. Type: Pattern / Pitfall / Preference / Architecture
2. Key: short identifier
3. Insight: the learning itself
4. Confidence: HIGH / MEDIUM / LOW
5. Related files (optional)

Save to `.gstack/projects/$SLUG/learnings.jsonl`

## Proactive Trigger Rules

Invoke this skill when:
- User asks "didn't we fix this before?" or "what have we learned?"
- User wants to see project patterns/pitfalls
- User asks about past decisions or conventions
