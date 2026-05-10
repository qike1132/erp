# /plan-eng-review — Engineering Plan Review (Comate Adapted)

> Lock architecture, data flow, edge cases, test requirements, and performance considerations. Opinionated recommendations, not just observations.

## Required Checklist

Every eng review MUST cover all 5 sections. NEVER skip or compress the test review.

### 1. Scope Challenge

Before reviewing architecture, challenge whether the plan maps correctly to existing code:

- **Read actual code** — not just the plan's description of it
- **Map sub-problems to existing code** — which files/functions already solve parts of this?
- **Check for scope creep** — is the plan solving problems that don't exist?
- **Check for missing scope** — is the plan ignoring parts of the blast radius?
- **Second-order effects** — "If we do X, what happens to Y? And then what happens because Y changed?"
- **Coupling radar** — "Which other systems will need to change if we change this?"
- **Failure mode anticipation** — "What happens when this fails? And then what?"

### 2. Architecture Review

For each architectural decision in the plan:

1. **State the decision explicitly** — don't assume it's obvious
2. **Identify the alternatives considered** — why was this approach chosen?
3. **Check coupling** — which components depend on this decision? How hard to change later?
4. **Check reversibility** — is this a one-way door or two-way door? If one-way, is the evidence strong enough?

**Produce an ASCII dependency graph** showing component relationships:
```
[AuthService] ──→ [UserDB]
     │
     ├──→ [SessionCache]
     │
     └──→ [APIGateway] ──→ [OrderService] ──→ [OrderDB]
```

Evaluate:
- **Coupling** — which components are tightly coupled? Should they be?
- **Scaling** — where are the bottlenecks? What breaks at 10x traffic?
- **Security** — where are the trust boundaries? What needs authentication?

### 3. Code Quality Review

Identify issues in the proposed implementation:
- **DRY violations** — same logic in multiple places
- **Naming** — unclear or inconsistent names
- **Complexity** — functions > 50 lines, nesting > 3 levels
- **Error handling** — missing error cases, swallowed errors
- **Type safety** — any types, type assertions, missing validation
- **Dead code** — unused imports, unreachable paths

### 4. Test Review — NEVER SKIP OR COMPRESS

**This section is MANDATORY.** It is NEVER acceptable to skip it, compress it to a one-liner, or write "tests look good."

1. **Read actual code** — understand what codepaths exist
2. **Build a test diagram** — map every codepath to a test case:

```
Codepath → Test Required → Test Exists? → Coverage Gap?
─────────────────────────────────────────────────────────
POST /api/orders (happy) → Integration test → No → YES
POST /api/orders (invalid) → Unit test → No → YES
POST /api/orders (unauth) → Integration test → Yes → No
```

3. **Categorize test requirements:**

**Happy Path Tests** (MUST have):
- Core workflow end-to-end
- Each API endpoint with valid input
- Each user-facing feature

**Sad Path Tests** (MUST have):
- Each validation rule with invalid input
- Each error handler
- Authentication/authorization failures

**Integration Tests** (MUST have):
- Cross-service interactions
- Database operations (not mocked)
- External API calls (with contract tests)

**Performance Tests** (if relevant):
- Expected load capacity
- Response time under load
- Database query performance

### 5. Performance Review

Identify potential bottlenecks systematically:
- **N+1 queries** — any loop that makes a query per iteration
- **Missing indexes** — queries filtering/sorting without index support
- **Large data transfers** — sending entire tables when pagination would work
- **Synchronous operations that should be async** — blocking I/O, long computations
- **Memory-intensive operations** — loading entire datasets into memory
- **Hot paths that need optimization** — code on the critical request path
- **Caching opportunities** — data that's read often but rarely changes

## Data Flow Mapping

Trace data through the system:
```
[Input source] → [Validation] → [Transform] → [Storage] → [Retrieval] → [Output]
```

For each step, verify:
- Schema is defined (what shape is the data?)
- Validation exists (what could go wrong?)
- Transform is correct (are there edge cases?)
- Storage is appropriate (performance, consistency, durability)
- Retrieval is efficient (indexes, query patterns)
- Output is correct (format, completeness, timeliness)

## Edge Case Enumeration

Systematically identify boundary conditions:

### Input Edge Cases
- Empty input, null, undefined
- Maximum size/length inputs
- Unicode, special characters, encoding issues
- Concurrent identical requests

### State Edge Cases
- First user ever (empty state)
- Millionth user (scale)
- Deleted data referenced by other data
- Stale data (cache invalidation)
- Migration during active usage

### Failure Edge Cases
- Network timeout / partition
- Database connection loss
- Disk full
- Memory pressure
- Dependent service down

### Time Edge Cases
- Timezone handling
- Daylight saving transitions
- Clock skew between services
- Long-running operations

## Output Format

```
## Engineering Review

### Architecture Decisions
| Decision | Alternatives | Coupling | Reversibility | Confidence |
|----------|-------------|---------|---------------|------------|
| [Decision] | [Alts] | [Low/Med/High] | [One/Two-way] | [High/Med/Low] |

### Dependency Graph
[ASCII diagram]

### Data Flow
[Structured description with validation at each step]

### Critical Edge Cases
1. [Edge case] → [Handling plan] → [Test required?]

### Test Diagram
[Every codepath mapped to test requirement]

### Test Requirements (MUST)
- [ ] [Test 1]
- [ ] [Test 2]

### Performance Concerns
1. [Concern] → [Mitigation]

### Failure Modes Registry
1. [Failure mode] → [Likelihood] → [Impact] → [Mitigation]

### Risks
1. [Risk] → [Likelihood: High/Med/Low] → [Impact: High/Med/Low] → [Mitigation]

### TODOS.md Updates
- [Add any items discovered during review]
```

## Important Rules

- **Test review is NEVER optional.** Every codepath must be mapped.
- **Read actual code.** Don't review the plan in a vacuum — check what exists.
- **Produce the dependency graph.** It's not optional decoration — it forces you to think about coupling.
- **Edge cases are systematic.** Don't just list the ones you happen to think of — go through each category.
- **Performance review must check for N+1.** This is the most common and most damaging performance issue.
