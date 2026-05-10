# /ship — Fully Automated Ship Workflow (Comate Adapted)

> Run tests, review, bump VERSION, update CHANGELOG, commit, push, create PR. Non-interactive — DO IT.

**This is a non-interactive, fully automated workflow.** Do NOT ask for confirmation at routine steps. The user said `/ship` which means DO IT.

**Only stop for:**
- On the base branch (abort)
- Merge conflicts that can't be auto-resolved
- In-branch test failures
- Pre-landing review finds ASK items that need user judgment
- MINOR or MAJOR version bump needed
- AI-assessed coverage below minimum threshold
- Plan items NOT DONE with no user override

**Never stop for:**
- Uncommitted changes (always include them)
- Version bump choice (auto-pick MICRO or PATCH)
- CHANGELOG content (auto-generate from diff)
- Commit message approval (auto-commit)
- Auto-fixable review findings (fixed automatically)

**Re-run behavior:** Re-running `/ship` means "run the whole checklist again." Every verification step runs on every invocation. Only *actions* are idempotent (if VERSION already bumped, skip; if already pushed, skip push; if PR exists, update body).

---

## Step 1: Pre-flight

1. If on the base branch: **abort** — "You're on the base branch. Ship from a feature branch."
2. Check `git status`. Uncommitted changes are always included — no need to ask.
3. Run `git diff <base>...HEAD --stat` and `git log <base>..HEAD --oneline` to understand what's being shipped.
4. **Review Readiness Dashboard:** Check for prior eng reviews. If no prior eng review found, note: "No prior eng review found — ship will run its own pre-landing review in Step 9." If diff >200 lines, recommend `/plan-eng-review` or `/autoplan` before shipping. CEO and Design reviews are informational, never block.

---

## Step 2: Distribution Pipeline Check

If the diff introduces a new standalone artifact (CLI binary, library package, tool), verify that a distribution pipeline exists.

1. Check if the diff adds a new `cmd/` directory, `main.go`, or `bin/` entry point.
2. If new artifact detected, check for a release workflow (`.github/workflows/` with release/publish/deploy).
3. **If no release pipeline exists and a new artifact was added:** Ask user: A) Add a release workflow now, B) Defer to TODOS.md, C) Not needed.

---

## Step 3: Merge the Base Branch

Fetch and merge the base branch into the feature branch so tests run against the merged state:

```bash
git fetch origin <base> && git merge origin/<base> --no-edit
```

If merge conflicts: try auto-resolving simple ones (VERSION, CHANGELOG ordering). Complex conflicts → STOP and show them.

---

## Step 4: Test Framework Bootstrap (if needed)

**Detect existing test framework:**

1. Check for config files: `jest.config.*`, `vitest.config.*`, `.rspec`, `pytest.ini`, `phpunit.xml`
2. Check for test directories: `test/`, `tests/`, `spec/`, `__tests__/`
3. Check CLAUDE.md for `## Testing` section

**If test framework detected:** Read 2-3 existing test files to learn conventions. Skip bootstrap.

**If NO test framework detected:** Offer to bootstrap. If user declines, continue without tests.

**Bootstrap steps:**
1. Research current best practices for the detected runtime (use web search if available, otherwise use built-in knowledge)
2. Present framework options to user (primary + alternative)
3. Install and configure chosen framework
4. Generate 3-5 real tests for recently changed files
5. Create TESTING.md and update CLAUDE.md
6. Commit as `chore: bootstrap test framework ({name})`

---

## Step 5: Run Tests

Run the project's test suite against the merged code.

**If any test fails:** Do NOT immediately stop. Apply the Test Failure Ownership Triage:

### Test Failure Ownership Triage

For each failing test:

1. **Classify:** Is it an **in-branch** failure (the diff caused it) or **pre-existing** (unrelated to branch changes)?
   - When ambiguous, default to in-branch — safer to stop the developer than let broken tests ship.

2. **In-branch failures:** STOP. Show them. Developer must fix their own broken tests.

3. **Pre-existing failures:** Ask user how to handle:
   - A) Investigate and fix now (recommended for solo repos)
   - B) Add as P0 TODO
   - C) Blame + assign GitHub issue (collaborative repos)
   - D) Skip — ship anyway

**After triage:** If any in-branch failures remain unfixed, STOP. Otherwise continue.

---

## Step 6: Eval Suites (conditional)

If the diff touches prompt-related files (LLM prompt builders, generation services, system prompts, eval infrastructure), run affected eval suites at full tier. Skip entirely if no prompt files in the diff.

**If any eval fails:** STOP. Do not proceed.

---

## Step 7: Test Coverage Audit

Trace every codepath changed in the diff and map test coverage.

**Process:**
1. Read every changed file. Trace data flow through the code.
2. Map user flows, interaction edge cases, and error states.
3. Check each branch against existing tests. Quality score:
   - ★★★ Tests behavior with edge cases AND error paths
   - ★★ Tests correct behavior, happy path only
   - ★ Smoke test / trivial assertion
4. Output ASCII coverage diagram showing tested vs. untested paths.
5. Generate tests for uncovered paths (cap: 30 code paths, 20 tests max).

### REGRESSION RULE (mandatory)

**IRON LAW:** When the coverage audit identifies a REGRESSION — code that previously worked but the diff broke — a regression test is written immediately. No asking. No skipping.

### Coverage Gate

Check for `## Test Coverage` section in CLAUDE.md with Minimum/Target fields. Defaults: Minimum = 60%, Target = 80%.

- **>= target:** Pass.
- **>= minimum, < target:** Ask user: generate more tests, accept risk, or mark intentionally uncovered.
- **< minimum:** Ask user: generate tests or override with risk acceptance.
- **100%:** Pass.

---

## Step 8: Plan Completion Audit

If a plan file is found (from conversation context or file search):

1. Extract every actionable item (checkboxes, numbered steps, imperative statements, file specs, test requirements, data model changes).
2. Classify how each item can be verified: DIFF-VERIFIABLE, CROSS-REPO, EXTERNAL-STATE, CONTENT-SHAPE.
3. Cross-reference against the diff. Classify each: DONE, PARTIAL, NOT DONE, CHANGED, UNVERIFIABLE.

**Apply the path concreteness rule:** If a plan item names a concrete filesystem path, it MUST be classified DONE or NOT DONE — not UNVERIFIABLE just because checking is inconvenient.

**Gate logic (priority order):**
1. **NOT DONE items:** Ask user: A) Stop and implement, B) Ship + create P1 TODOs, C) Intentionally dropped.
2. **UNVERIFIABLE items:** Confirm each individually (not blanket). Per-item: Y) Confirmed done, N) Not done (blocks ship), D) Intentionally dropped.
3. **Only PARTIAL items:** Continue with note in PR body.
4. **All DONE or CHANGED:** Pass.

---

## Step 8.2: Scope Drift Detection

Before reviewing code quality: **did they build what was requested — nothing more, nothing less?**

1. Read TODOS.md, PR description, commit messages. Identify stated intent.
2. Compare files changed against stated intent.
3. Evaluate for SCOPE CREEP (unrelated changes) and MISSING REQUIREMENTS.
4. Output: `Scope Check: [CLEAN / DRIFT DETECTED / REQUIREMENTS MISSING]`

This is INFORMATIONAL — does not block the review.

---

## Step 9: Pre-Landing Review

Review the diff for structural issues that tests don't catch.

1. Run `git diff origin/<base>` to get the full diff.
2. Apply the review in two passes:
   - **CRITICAL:** SQL & Data Safety, LLM Output Trust Boundary, Shell Injection, Enum & Value Completeness
   - **INFORMATIONAL:** Race Conditions, API Contract, Async/Sync Mixing, Type Coercion, etc.

### Confidence Calibration

Every finding includes a confidence score (1-10):
- 9-10: Show normally
- 7-8: Show normally
- 5-6: Show with caveat
- 3-4: Appendix only
- 1-2: Suppress (unless P0)

### Fix-First Review

1. **Classify each finding** as AUTO-FIX or ASK. Critical → ASK. Informational → AUTO-FIX.
2. **Auto-fix all AUTO-FIX items.** Output: `[AUTO-FIXED] [file:line] Problem → fix`
3. **Batch-ask about ASK items** in ONE question with per-item options and overall RECOMMENDATION.
4. **Apply user-approved fixes.** If ANY fixes were applied: commit fixed files, then STOP and tell user to re-run `/ship`. If no fixes: continue.

### Design Review (conditional)

If the diff touches frontend files:
1. Check for DESIGN.md — calibrate findings against it.
2. Apply design checklist against changed frontend files.
3. Include findings in review output, merging with code review findings.

---

## Step 11: Adversarial Review (always-on)

Every diff gets adversarial review. LOC is not a proxy for risk — a 5-line auth change can be critical.

### Claude Adversarial Subagent (always runs)

Dispatch an independent subagent with fresh context — no checklist bias. Prompt:

"Read the diff for this branch. Think like an attacker and a chaos engineer. Find ways this code will fail in production. Look for: edge cases, race conditions, security holes, resource leaks, failure modes, silent data corruption, error handling that swallows failures, trust boundary violations. Be adversarial. Be thorough. No compliments. For each finding, classify as FIXABLE or INVESTIGATE. End with: `Recommendation: <action> because <one-line reason naming the most exploitable finding>`"

FIXABLE findings flow into Fix-First. INVESTIGATE findings are informational.

### Cross-Model Synthesis

After all passes, synthesize:
```
ADVERSARIAL REVIEW SYNTHESIS:
  High confidence (found by multiple sources): [...]
  Unique to structured review: [...]
  Unique to adversarial: [...]
```

---

## Step 12: Version Bump (auto-decide)

1. Read the current `VERSION` file (4-digit format: `MAJOR.MINOR.PATCH.MICRO`).

2. **Auto-decide the bump level based on the diff:**
   - **MICRO** (4th digit): < 50 lines changed, trivial tweaks, typos, config
   - **PATCH** (3rd digit): 50+ lines changed, no feature signals
   - **MINOR** (2nd digit): **ASK** if ANY feature signal (new routes, new DB migrations, new modules) or 500+ lines
   - **MAJOR** (1st digit): **ASK** — only for milestones or breaking changes

3. **Idempotency:** If VERSION already bumped vs. base branch, skip the bump. Check for drift between VERSION and package.json — repair if needed.

4. Write new version to both `VERSION` and `package.json`.

---

## Step 13: CHANGELOG (auto-generate)

1. Read existing CHANGELOG.md header to know the format.
2. Enumerate every commit on the branch: `git log <base>..HEAD --oneline`
3. Read the full diff to understand what each commit actually changed.
4. Group commits by theme: new features, performance, bug fixes, cleanup, infra, refactoring.
5. Write the CHANGELOG entry covering ALL groups. Categorize: `### Added`, `### Changed`, `### Fixed`, `### Removed`.
6. **Cross-check:** Every commit must map to at least one bullet point.

**Voice:** Lead with what the user can now **do**. Plain language, not implementation details.

---

## Step 14: TODOS.md (auto-update)

Cross-reference TODOS.md against changes being shipped.

1. If TODOS.md missing: ask user whether to create one.
2. If disorganized (no priority fields, no component groupings): ask whether to reorganize.
3. Detect completed TODOs automatically from the diff and commit history. Be conservative — only mark as completed with clear evidence.
4. Move completed items to `## Completed` section with version and date.

---

## Step 15: Commit (bisectable chunks)

**Goal:** Create small, logical commits that work well with `git bisect`.

1. Analyze the diff and group changes into logical commits. Each commit = **one coherent change**.

2. **Commit ordering:**
   - Infrastructure: migrations, config, route additions
   - Models & services: new models, services (with their tests)
   - Controllers & views: controllers, views, components (with their tests)
   - VERSION + CHANGELOG + TODOS.md: always in the final commit

3. **Rules:**
   - Model + its test → same commit
   - Service + its test → same commit
   - Small diff (< 50 lines, < 4 files) → single commit is fine
   - Each commit must be independently valid (no broken imports)

4. Each commit message: `<type>: <summary>` (feat/fix/chore/refactor/docs)

---

## Step 16: Verification Gate

**IRON LAW: NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE.**

Before pushing, re-verify if code changed during Steps 4-6:

1. **Test verification:** If ANY code changed after Step 5's test run, re-run the test suite.
2. **Build verification:** If the project has a build step, run it.
3. **Rationalization prevention:**
   - "Should work now" → RUN IT.
   - "I'm confident" → Confidence is not evidence.
   - "I already tested earlier" → Code changed since then. Test again.

**If tests fail here:** STOP. Fix and return to Step 5.

---

## Step 17: Push

```bash
git push -u origin <branch-name>
```

**Idempotency:** If already pushed and up to date, skip but continue.

---

## Step 18: Documentation Sync

Run the `/document-release` methodology to update project docs (README, CLAUDE.md, etc.) to match what shipped. This runs BEFORE PR creation so the documentation section is baked into the initial PR body.

If no documentation files needed updating, skip.

---

## Step 19: Create PR

If a PR already exists for this branch: **update** the body and title using fresh results. Always regenerate from scratch.

**PR title MUST start with `v$NEW_VERSION`.** Format: `v<VERSION> <type>: <summary>`

**PR body sections:**

```
## Summary
<All changes being shipped, grouped by theme. Every substantive commit must appear.>

## Test Coverage
<Coverage diagram from Step 7, or "All new code paths have test coverage.">

## Pre-Landing Review
<Findings from Step 9, or "No issues found.">

## Design Review
<If design review ran: findings summary. If no frontend files: "skipped.">

## Scope Drift
<Scope Check result>

## Plan Completion
<Completion checklist from Step 8, or "No plan file detected.">

## TODOS
<Completed items with version, or "No TODO items completed.">

## Documentation
<Updates from Step 18, or omit if none.>

## Test plan
- [x] All tests pass (N runs, 0 failures)
```

**Platform-specific:**
- GitHub: `gh pr create --base <base> --title "v$NEW_VERSION <type>: <summary>" --body "..."`
- GitLab: `glab mr create -b <base> -t "v$NEW_VERSION <type>: <summary>" -d "..."`
- Neither available: Print branch name, remote URL, and instruct user to create manually.

**Output the PR/MR URL.**

---

## Important Rules

- **Never skip tests.** If tests fail, stop.
- **Never skip the pre-landing review.**
- **Never force push.** Use regular `git push` only.
- **Never ask for trivial confirmations** (ready to push?, create PR?). DO stop for: version bumps (MINOR/MAJOR), pre-landing ASK items, coverage gate failures.
- **Always use the 4-digit version format** from the VERSION file.
- **Split commits for bisectability** — each commit = one logical change.
- **TODOS.md completion detection must be conservative.** Only mark items completed when the diff clearly shows the work.
- **Never push without fresh verification evidence.** If code changed after tests, re-run before pushing.
- **The goal is: user says `/ship`, next thing they see is the review + PR URL + auto-synced docs.**

## Proactive Trigger Rules

Invoke this skill when:
- User says "ship it", "deploy", "create a PR"
- User says code is ready
- User asks about deploying or pushing code
