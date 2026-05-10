# /review — Pre-Landing PR Review (Comate Adapted)

> Analyzes the current branch's diff against the base branch for structural issues that tests don't catch. Fix-first, not read-only.

## Step 1: Check Branch

1. Get the current branch: `git branch --show-current`
2. If on the base branch, output: **"Nothing to review — you're on the base branch or have no changes against it."** and stop.
3. Fetch and check for diff: `git fetch origin <base> --quiet && git diff origin/<base> --stat`. If no diff, stop with the same message.

---

## Step 1.5: Scope Drift Detection

Before reviewing code quality, check: **did they build what was requested — nothing more, nothing less?**

1. Read `TODOS.md` (if it exists). Read PR description if available. Read commit messages (`git log origin/<base>..HEAD --oneline`).
2. Identify the **stated intent** — what was this branch supposed to accomplish?
3. Run `git diff origin/<base>...HEAD --stat` and compare the files changed against the stated intent.

4. Evaluate with skepticism:

   **SCOPE CREEP detection:**
   - Files changed that are unrelated to the stated intent
   - New features or refactors not mentioned in the plan
   - "While I was in there..." changes that expand blast radius

   **MISSING REQUIREMENTS detection:**
   - Requirements from TODOS.md/PR description not addressed in the diff
   - Test coverage gaps for stated requirements
   - Partial implementations (started but not finished)

5. Output (before the main review begins):
   ```
   Scope Check: [CLEAN / DRIFT DETECTED / REQUIREMENTS MISSING]
   Intent: <1-line summary of what was requested>
   Delivered: <1-line summary of what the diff actually does>
   [If drift: list each out-of-scope change]
   [If missing: list each unaddressed requirement]
   ```

6. This is **INFORMATIONAL** — does not block the review. Proceed to the next step.

---

## Step 2: Plan File Discovery & Completion Audit

### Plan File Discovery

1. **Conversation context (primary):** Check if there is an active plan file in this conversation.
2. **Content-based search (fallback):** Search common plan file locations for plans mentioning the current branch or repo name. Validate by reading the first 20 lines — if from a different project, treat as "no plan file found."
3. If no plan file found → skip with "No plan file detected — skipping completion audit."

### Actionable Item Extraction

Read the plan file. Extract every actionable item:

- **Checkbox items:** `- [ ] ...` or `- [x] ...`
- **Numbered steps** under implementation headings
- **Imperative statements:** "Add X to Y", "Create a Z service"
- **File-level specifications:** "New file: path/to/file.ts"
- **Test requirements:** "Test that X", "Add test for Y"
- **Data model changes:** "Add column X to table Y"

**Ignore:** Context/Background sections, Questions/open items (TBD, TODO: decide), Review report sections, Explicitly deferred items (Future:, Out of scope:, P2/P3/P4:), CEO Review Decisions sections.

**Cap:** Extract at most 50 items.

For each item, note:
- The item text (verbatim or concise summary)
- Its category: CODE | TEST | MIGRATION | CONFIG | DOCS

### Verification Mode

Before judging completion, classify HOW each item can be verified:

- **DIFF-VERIFIABLE** — A code change in this repo would manifest in `git diff`. Examples: "add UserService" (file appears), "validate input X" (validation logic appears).
- **CROSS-REPO** — Item names a file or change in a sibling repo. The current diff CANNOT prove this.
- **EXTERNAL-STATE** — Item names state in an external system (Supabase config, Cloudflare DNS, Vercel env vars). The current diff CANNOT prove this.
- **CONTENT-SHAPE** — Item requires a file to follow a specific convention. If in this repo: diff-verifiable. If in another repo: see CROSS-REPO / EXTERNAL-STATE.

**Verification dispatch:**
- **DIFF-VERIFIABLE** → cross-reference against diff.
- **CROSS-REPO** → if sibling repo reachable on disk, check file existence. File exists → DONE. Missing → NOT DONE. Unreachable → UNVERIFIABLE.
- **EXTERNAL-STATE** → UNVERIFIABLE. Cite what needs manual check.
- **CONTENT-SHAPE in another repo** → check validators if available, otherwise UNVERIFIABLE.

**Path concreteness rule.** If a plan item names a *concrete filesystem path*, it MUST be classified DONE or NOT DONE based on file existence. UNVERIFIABLE is only valid when the path is genuinely abstract or unreachable. "I don't want to check" is not unreachable.

**Honesty rule.** Do NOT classify an item as DONE just because related code shipped. Code that *handles* a deliverable is not the deliverable. When in doubt between DONE and UNVERIFIABLE, prefer UNVERIFIABLE.

### Cross-Reference Against Diff

For each extracted plan item, classify:

- **DONE** — Clear evidence the item shipped. Cite specific file(s) changed.
- **PARTIAL** — Some work toward this item exists but is incomplete.
- **NOT DONE** — Verification ran and produced negative evidence.
- **CHANGED** — The item was implemented using a different approach than the plan described, but the same goal is achieved.
- **UNVERIFIABLE** — The diff cannot prove or disprove this. Cite the specific manual verification needed.

**Be conservative with DONE** — require clear evidence.
**Be generous with CHANGED** — if the goal is met by different means, that counts as addressed.
**Be honest with UNVERIFIABLE** — better to surface 5 items the user must manually confirm than silently classify them DONE.

### Output Format

```
PLAN COMPLETION AUDIT
═══════════════════════════════
Plan: {plan file path}

## Implementation Items
  [DONE]         Create UserService — src/services/user_service.rb (+142 lines)
  [PARTIAL]      Add validation — model validates but missing controller checks
  [NOT DONE]     Add caching layer — no cache-related changes in diff
  [CHANGED]      "Redis queue" → implemented with Sidekiq instead

## Test Items
  [DONE]         Unit tests for UserService — test/services/user_service_test.rb
  [NOT DONE]     E2E test for signup flow

## Cross-Repo / External Items
  [DONE]         sibling-repo has /docs/dashboard.md — verified at ~/Development/sibling-repo/docs/dashboard.md
  [UNVERIFIABLE] Cloudflare DNS-only on api.example.com — external system, manual check required

─────────────────────────────────
COMPLETION: 5/9 DONE, 1 PARTIAL, 1 NOT DONE, 1 CHANGED, 2 UNVERIFIABLE
─────────────────────────────────
```

### Investigation Depth

For each PARTIAL or NOT DONE item, investigate WHY:
1. Check git log for commits that suggest the work was started, attempted, or reverted
2. Read relevant code to understand what was built instead
3. Determine the likely reason:
   - **Scope cut** — evidence of intentional removal (revert commit, removed TODO)
   - **Context exhaustion** — work started but stopped mid-way
   - **Misunderstood requirement** — something was built but doesn't match the plan
   - **Blocked by dependency** — plan item depends on something unavailable
   - **Genuinely forgotten** — no evidence of any attempt

Output for each discrepancy:
```
DISCREPANCY: {PARTIAL|NOT_DONE} | {plan item} | {what was actually delivered}
INVESTIGATION: {likely reason with evidence from git log / code}
IMPACT: {HIGH|MEDIUM|LOW} — {what breaks or degrades if this stays undelivered}
```

### Integration with Scope Drift Detection

- **NOT DONE items** become additional evidence for **MISSING REQUIREMENTS** in the scope drift report.
- **Items in the diff that don't match any plan item** become evidence for **SCOPE CREEP** detection.
- **HIGH-impact discrepancies** gate via user question: show findings, options: A) Stop and implement missing items, B) Ship anyway + create P1 TODOs, C) Intentionally dropped.

### Fallback Intent Sources (when no plan file found)

1. **Commit messages:** Extract real intent from actionable verbs ("add", "implement", "fix"). Skip noise: "WIP", "tmp", "squash", "merge".
2. **TODOS.md:** Check for items related to this branch or recent dates.
3. **PR description:** If available, for intent context.

---

## Step 3: Get the Diff

Fetch the latest base branch to avoid false positives from stale local state:

```bash
git fetch origin <base> --quiet
```

Run `git diff origin/<base>` to get the full diff.

---

## Step 4: Critical Pass (Core Review)

Apply these categories against the diff:

### SQL & Data Safety
- String interpolation in queries → SQL injection
- ORM raw queries without parameterization
- Missing transaction boundaries for multi-step operations

### Race Conditions & Concurrency
- Shared mutable state without synchronization
- Check-then-act patterns without locks
- Async operations with missing await/error handling

### LLM Output Trust Boundary
- User input fed directly to LLM prompts without sanitization
- LLM output used for file paths, commands, or SQL without validation
- System prompts that can be overridden by user content

### Shell Injection
- Command injection: system(), exec(), spawn(), popen
- Untrusted input in shell commands

### Enum & Value Completeness
**Requires reading code OUTSIDE the diff.** When the diff introduces a new enum value, status, tier, or type constant, search for all files that reference sibling values, then read those files to check if the new value is handled.

### Additional Categories (INFORMATIONAL)
- Async/Sync Mixing
- Column/Field Name Safety
- LLM Prompt Issues
- Type Coercion
- View/Frontend
- Time Window Safety
- Completeness Gaps
- Distribution & CI/CD
- API Contract Violations (breaking changes to public APIs, missing error responses, response format changes without versioning)
- Conditional Side Effects (side effects in error handlers, missing cleanup in error paths, operations that should be atomic but aren't)

**Search-before-recommending:** When recommending a fix pattern (especially for concurrency, caching, auth, or framework-specific behavior):
- Verify the pattern is current best practice for the framework version in use
- Check if a built-in solution exists in newer versions before recommending a workaround
- Verify API signatures against current docs

---

## Confidence Calibration

Every finding MUST include a confidence score (1-10):

| Score | Meaning | Display rule |
|-------|---------|-------------|
| 9-10 | Verified by reading specific code. Concrete bug or exploit demonstrated. | Show normally |
| 7-8 | High confidence pattern match. Very likely correct. | Show normally |
| 5-6 | Moderate. Could be a false positive. | Show with caveat: "Medium confidence, verify this is actually an issue" |
| 3-4 | Low confidence. Pattern is suspicious but may be fine. | Suppress from main report. Include in appendix only. |
| 1-2 | Speculation. | Only report if severity would be P0. |

**Finding format:**

`[SEVERITY] (confidence: N/10) file:line — description`

Example:
`[P1] (confidence: 9/10) app/models/user.rb:42 — SQL injection via string interpolation in where clause`

---

## Step 5: Fix-First Review

**Every finding gets action — not just critical ones.**

### Step 5a: Classify each finding

For each finding, classify as AUTO-FIX or ASK:
- Critical findings lean toward ASK
- Informational findings lean toward AUTO-FIX
- Any finding with a recommended test gets reclassified as ASK (show the proposed test code)

### Step 5b: Auto-fix all AUTO-FIX items

Apply each fix directly. For each one, output a one-line summary:
`[AUTO-FIXED] [file:line] Problem → what you did`

### Step 5c: Batch-ask about ASK items

If there are ASK items remaining, present them in ONE question:

- List each item with a number, the severity label, the problem, and a recommended fix
- For each item, provide options: A) Fix as recommended, B) Skip
- Include an overall RECOMMENDATION

Example format:
```
I auto-fixed 5 issues. 2 need your input:

1. [CRITICAL] app/models/post.rb:42 — Race condition in status transition
   Fix: Add `WHERE status = 'draft'` to the UPDATE
   → A) Fix  B) Skip

2. [INFORMATIONAL] app/services/generator.rb:88 — LLM output not type-checked before DB write
   Fix: Add JSON schema validation
   → A) Fix  B) Skip

RECOMMENDATION: Fix both — #1 is a real race condition, #2 prevents silent data corruption.
```

### Step 5d: Apply user-approved fixes

Apply fixes for items where the user chose "Fix." Output what was fixed.

### Verification of Claims

Before producing the final review output:
- If you claim "this pattern is safe" → cite the specific line proving safety
- If you claim "this is handled elsewhere" → read and cite the handling code
- If you claim "tests cover this" → name the test file and method
- Never say "likely handled" or "probably tested" — verify or flag as unknown

**Rationalization prevention:** "This looks fine" is not a finding. Either cite evidence it IS fine, or flag it as unverified.

---

## Step 5.5: TODOS Cross-Reference

Read `TODOS.md` in the repository root (if it exists). Cross-reference the PR against open TODOs:

- **Does this PR close any open TODOs?** If yes, note: "This PR addresses TODO: <title>"
- **Does this PR create work that should become a TODO?** If yes, flag as informational finding.
- **Are there related TODOs that provide context for this review?** Reference them when discussing related findings.

---

## Step 5.6: Documentation Staleness Check

Cross-reference the diff against documentation files. For each `.md` file in the repo root (README.md, ARCHITECTURE.md, CONTRIBUTING.md, CLAUDE.md, etc.):

1. Check if code changes in the diff affect features, components, or workflows described in that doc.
2. If the doc was NOT updated in this branch but the code it describes WAS changed, flag as INFORMATIONAL:
   "Documentation may be stale: [file] describes [feature/component] but code changed in this branch. Consider running `/document-release`."

This is informational only — never critical.

---

## Adversarial Review (Always-On)

Every diff gets adversarial review. LOC is not a proxy for risk — a 5-line auth change can be critical.

### Claude Adversarial Subagent (always runs)

Dispatch an independent subagent with fresh context — no checklist bias from the structured review. This genuine independence catches things the primary reviewer is blind to.

Subagent prompt:
"Read the diff for this branch with `git diff origin/<base>`. Think like an attacker and a chaos engineer. Your job is to find ways this code will fail in production. Look for: edge cases, race conditions, security holes, resource leaks, failure modes, silent data corruption, logic errors that produce wrong results silently, error handling that swallows failures, and trust boundary violations. Be adversarial. Be thorough. No compliments — just the problems. For each finding, classify as FIXABLE (you know how to fix it) or INVESTIGATE (needs human judgment). After listing findings, end your output with ONE line: `Recommendation: <action> because <one-line reason naming the most exploitable finding>`"

Present findings under an `ADVERSARIAL REVIEW (Claude subagent):` header. **FIXABLE findings** flow into the same Fix-First pipeline. **INVESTIGATE findings** are presented as informational.

### Cross-Model Synthesis

After all passes complete, synthesize findings across all sources:

```
ADVERSARIAL REVIEW SYNTHESIS (always-on, N lines):
════════════════════════════════════════════════════════════
  High confidence (found by multiple sources): [findings agreed on by >1 pass]
  Unique to Claude structured review: [from earlier step]
  Unique to Claude adversarial: [from subagent]
════════════════════════════════════════════════════════════
```

High-confidence findings (agreed on by multiple sources) should be prioritized for fixes.

---

## Output Format

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

## Capture Learnings

If you discovered a non-obvious pattern, pitfall, or architectural insight during this session, note it for future reference:

- **Types:** pattern (reusable approach), pitfall (what NOT to do), preference (user stated), architecture (structural decision), tool (library/framework insight), operational (project environment/CLI/workflow knowledge).
- **Confidence:** 1-10. Be honest. An observed pattern you verified in the code is 8-9. An inference you're not sure about is 4-5. A user preference they explicitly stated is 10.
- **Only log genuine discoveries.** Don't log obvious things. Would this insight save time in a future session? If yes, log it.

## Important Rules

- **Read the FULL diff before commenting.** Do not flag issues already addressed in the diff.
- **Fix-first, not read-only.** AUTO-FIX items are applied directly. ASK items are only applied after user approval. Never commit, push, or create PRs — that's /ship's job.
- **Be terse.** One line problem, one line fix. No preamble.
- **Only flag real problems.** Skip anything that's fine.
- **Path concreteness rule.** Every finding MUST reference a specific file and line. "A file has SQL injection" is REJECTED — find the actual line.

## Proactive Trigger Rules

Invoke this skill when:
- User says "review this PR" or "check my diff"
- User is about to merge or land code changes
- User asks for a sanity check before pushing
