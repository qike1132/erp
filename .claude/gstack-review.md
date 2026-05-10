# /review — Pre-landing PR Review (Comate Adapted)

> Finds bugs that pass CI but break in production. Focus on structural issues, not style.

## Step 1: Gather the Diff

```bash
git diff main...HEAD  # or appropriate base branch
```

Read the FULL diff. Do not skim.

## Step 2: Classification Framework

Classify every finding into one of:

| Category | Meaning | Verification |
|----------|---------|-------------|
| DIFF-VERIFIABLE | Can be confirmed from the diff alone | Read the changed code |
| CROSS-REPO | Requires checking other repos/packages | Search dependencies |
| EXTERNAL-STATE | Depends on runtime state, DB, API responses | Flag as unverified |
| CONTENT-SHAPE | About data format/structure | Trace data flow |

## Step 3: Path Concreteness Rule

Every finding MUST reference a specific file and line:
- GOOD: `src/auth/middleware.ts:42 — SQL query uses string interpolation`
- BAD: `A file has SQL injection` — REJECT this, find the actual line

Vague paths get flagged: "Path too vague — locate the specific line before reporting."

## Step 4: Validator Detection

When the diff claims something is validated/checked/sanitized:
1. Find the validator function
2. Verify it actually validates what's claimed
3. Check: is it called BEFORE the dangerous operation?
4. Check: does it cover all the edge cases?

Common validator failures:
- Validation exists but is bypassed in certain code paths
- Validation runs AFTER the dangerous operation
- Validation covers format but not semantics (e.g., "is it a URL?" vs "is it a SAFE URL?")

## Step 5: Structural Issue Scan

### SQL Safety
- String interpolation in queries → SQL injection
- ORM raw queries without parameterization
- Missing transaction boundaries for multi-step operations

### LLM Trust Boundary Violations
- User input fed directly to LLM prompts without sanitization
- LLM output used for file paths, commands, or SQL without validation
- System prompts that can be overridden by user content

### Conditional Side Effects
- Side effects in conditionally executed code (error handlers, callbacks)
- Missing cleanup in error paths (resource leaks)
- Operations that should be atomic but aren't

### Race Conditions
- Shared mutable state without synchronization
- Check-then-act patterns without locks
- Async operations with missing await/error handling

### API Contract Violations
- Breaking changes to public APIs
- Missing error responses for new error conditions
- Response format changes without versioning

## Step 6: Confusion Protocol

For high-stakes ambiguity (security, data loss, money):
1. STOP. Do not guess.
2. Present the ambiguity clearly: "I see two possible interpretations..."
3. Explain the consequences of each
4. Ask the user to clarify

## Step 7: Output Format

```
## Review Findings

### BLOCKER (must fix before merge)
- [VERIFIED] `file:line` — Description. Impact: what breaks. Fix: suggested approach.

### SUGGESTION (should fix)
- [VERIFIED] `file:line` — Description. Risk: what could go wrong. Fix: suggested approach.

### NIT (optional)
- `file:line` — Description.

### Unverified (needs manual check)
- [UNVERIFIED] `file:line` — Description. Why unverified: reason.
```

## Completeness Principle (Boil the Lake)

AI makes completeness cheap. For each finding:
- If a test is missing → recommend adding it (costs seconds, prevents regression)
- If an edge case is unhandled → recommend handling it (costs minutes, prevents production bug)
- If a complete approach costs 70 more lines than a 90% approach → recommend the complete one

## Proactive Trigger Rules

Invoke this skill when:
- User says "review this PR" or "check my diff"
- User is about to merge or land code changes
- User asks for a sanity check before pushing
