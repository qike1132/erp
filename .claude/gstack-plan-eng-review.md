# /plan-eng-review — Engineering Plan Review (Comate Adapted)

> Lock architecture, data flow, edge cases, and test requirements.

## Step 1: Architecture Lock

For each architectural decision in the plan:

1. **State the decision explicitly** — don't assume it's obvious
2. **Identify the alternatives considered** — why was this approach chosen?
3. **Check coupling** — which components depend on this decision? How hard to change later?
4. **Check reversibility** — is this a one-way door or two-way door? If one-way, is the evidence strong enough?

Cognitive patterns to apply:
- **Second-order effects**: "If we do X, what happens to Y? And then what happens because Y changed?"
- **Coupling radar**: "Which other systems will need to change if we change this?"
- **Failure mode anticipation**: "What happens when this fails? And then what?"

## Step 2: Data Flow Mapping

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

## Step 3: Edge Case Enumeration

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

## Step 4: Test Coverage Requirements

Define what MUST be tested (not nice-to-have, MUST):

### Happy Path Tests
- Core workflow end-to-end
- Each API endpoint with valid input

### Sad Path Tests
- Each validation rule with invalid input
- Each error handler
- Authentication/authorization failures

### Integration Tests
- Cross-service interactions
- Database operations (not mocked)
- External API calls (with contract tests)

### Performance Tests (if relevant)
- Expected load capacity
- Response time under load
- Database query performance

## Step 5: Performance Considerations

Identify potential bottlenecks:
- N+1 queries
- Missing indexes
- Large data transfers
- Synchronous operations that should be async
- Memory-intensive operations
- Hot paths that need optimization

## Output Format

```
## Engineering Review

### Architecture Decisions
| Decision | Alternatives | Coupling | Reversibility | Confidence |
|----------|-------------|---------|---------------|------------|
| [Decision] | [Alts] | [Low/Med/High] | [One/Two-way] | [High/Med/Low] |

### Data Flow
[ASCII diagram or structured description]

### Critical Edge Cases
1. [Edge case] → [Handling plan] → [Test required?]

### Test Requirements
- [ ] [Test 1]
- [ ] [Test 2]

### Performance Concerns
1. [Concern] → [Mitigation]

### Risks
1. [Risk] → [Likelihood: High/Med/Low] → [Impact: High/Med/Low] → [Mitigation]
```

## Proactive Trigger Rules

Invoke this skill when:
- User is planning a new feature or architecture change
- User asks for engineering review
- Before starting implementation of a complex feature
