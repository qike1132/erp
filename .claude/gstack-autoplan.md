# /autoplan — Auto-Review Pipeline (Comate Adapted)

> One command: rough plan in, fully reviewed plan out. Reads the full CEO, design, eng, and DX review skills from disk and follows them at full depth. Auto-decides intermediate questions using 6 decision principles. Surfaces taste decisions at a final approval gate.

## The 6 Decision Principles

Every intermediate question is auto-decided using these rules:

1. **Choose completeness** — Ship the whole thing. Pick the approach that covers more edge cases.
2. **Boil lakes** — Fix everything in the blast radius (files modified by this plan + direct importers). Auto-approve expansions that are in blast radius AND < 1 day effort (< 5 files, no new infra).
3. **Pragmatic** — If two options fix the same thing, pick the cleaner one. 5 seconds choosing, not 5 minutes.
4. **DRY** — Duplicates existing functionality? Reject. Reuse what exists.
5. **Explicit over clever** — 10-line obvious fix > 200-line abstraction. Pick what a new contributor reads in 30 seconds.
6. **Bias toward action** — Merge > review cycles > stale deliberation. Flag concerns but don't block.

**Conflict resolution:**
- CEO phase: P1 (completeness) + P2 (boil lakes) dominate
- Eng phase: P5 (explicit) + P3 (pragmatic) dominate
- Design phase: P5 (explicit) + P1 (completeness) dominate

## Decision Classification

Every auto-decision falls into three tiers:

**Mechanical** — one clearly right answer. Auto-decide silently. Examples: run outside voice review (always yes), reduce scope on a complete plan (always no).

**Taste** — reasonable people could disagree. Auto-decide with recommendation, but surface at the final gate. Three sources:
1. **Close approaches** — top two options are both viable with different tradeoffs
2. **Borderline scope** — in blast radius but 3-5 files, or ambiguous radius
3. **Cross-model disagreements** — outside voice recommends differently with a valid point

**User Challenge** — both models agree the user's stated direction should change. This is NEVER auto-decided. Presented at the final gate with richer context.

## Sequential Execution (MANDATORY)

Phases MUST execute in strict order: CEO → Design → Eng → DX. Each phase MUST complete fully before the next begins. NEVER run phases in parallel.

## What "Auto-Decide" Means

Auto-decide replaces the USER'S judgment with the 6 principles. It does NOT replace the ANALYSIS. Every section must still be executed at the same depth. The only thing that changes is who answers the questions: you do, using the 6 principles.

**Two exceptions — never auto-decided:**
1. Premises (Phase 1) — require human judgment about what problem to solve
2. User Challenges — when both models agree the user's stated direction should change

**You MUST still:** READ code/diffs/files, PRODUCE every required output, IDENTIFY every issue, DECIDE each issue using the 6 principles, LOG each decision, WRITE all required artifacts to disk.

**You MUST NOT:** Compress sections into one-liner table rows, write "no issues found" without showing what you examined, skip a section without stating what you checked and why.

## Phases

### Phase 0: Intake + Restore Point

1. **Capture restore point** — save the plan file's current state before doing anything
2. **Read context** — CLAUDE.md, TODOS.md, recent git log, git diff --stat
3. **Detect scope:**
   - **UI scope** — grep for view/rendering terms in the plan (require 2+ matches)
   - **DX scope** — grep for developer-facing terms (require 2+ matches, or trigger if product IS a developer tool)
4. **Load skill files from disk** — read plan-ceo-review, plan-design-review (if UI scope), plan-eng-review, plan-devex-review (if DX scope). Skip preamble and boilerplate sections.

### Phase 1: CEO Review (Strategy & Scope)

Follow `/plan-ceo-review` methodology — all sections, full depth.

**Mode:** SELECTIVE EXPANSION (hold scope + cherry-pick expansions).

**Premises:** Accept reasonable ones (P6), but **GATE: Present premises to user for confirmation** (the ONE question NOT auto-decided).

**Scope expansion rules:**
- In blast radius + <1d effort → approve (P2)
- Outside blast radius → defer to TODOS.md (P3)
- Duplicates existing functionality → reject (P4)
- Borderline (3-5 files) → mark TASTE DECISION

**Required outputs:** "NOT in scope" section, "What already exists" section, Error & Rescue Registry, Failure Modes Registry, Dream state delta, Completion Summary.

### Phase 2: Design Review (conditional — skip if no UI scope)

Follow `/plan-design-review` methodology — all 7 dimensions, full depth.

**Rules:**
- Structural issues: auto-fix (P5)
- Aesthetic/taste issues: mark TASTE DECISION
- Design system alignment: auto-fix if DESIGN.md exists and fix is obvious

**Required outputs:** All 7 pass scores with gap analysis, "NOT in scope" section, "What already exists" section, Completion Summary.

### Phase 3: Eng Review

Follow `/plan-eng-review` methodology — all sections, full depth.

**Scope challenge:** Never reduce (P2).

**Required checklist:**
1. Scope Challenge: Read actual code, map sub-problems to existing code
2. Architecture: Produce ASCII dependency graph. Evaluate coupling, scaling, security
3. Code Quality: Identify DRY violations, naming issues, complexity
4. **Test Review — NEVER SKIP OR COMPRESS:** Read actual code, build test diagram mapping every codepath
5. Performance: Evaluate N+1, memory, caching, slow paths

**Required outputs:** Architecture ASCII diagram, Test diagram, Failure modes registry, Completion Summary, TODOS.md updates.

### Phase 3.5: DX Review (conditional — skip if no developer-facing scope)

Follow `/plan-devex-review` methodology — all 8 DX dimensions, full depth.

**Mode:** DX POLISH.

**Required outputs:** Developer journey map, DX Scorecard with all dimension scores, TTHW assessment with target.

### Phase 4: Final Approval Gate

**STOP here and present the final state to the user.** Present:

1. **Plan Summary** (1-3 sentences)
2. **Decisions Made** (N total: M auto-decided, K taste choices, J user challenges)
3. **User Challenges** — for each: what user said, what models recommend, why, what we might be missing, cost if wrong. User's original direction stands unless explicitly changed.
4. **Taste Decisions** — for each: recommendation with principle, alternative with 1-sentence impact
5. **Auto-Decided decisions** (Decision Audit Trail)
6. **Review Scores** — CEO/Design/Eng/DX summaries
7. **Cross-Phase Themes** — concerns appearing in 2+ phases independently (high-confidence signal)
8. **Deferred to TODOS.md**

### Decision Audit Trail

Every auto-decision is logged:

```
| Decision | Principle | Mechanical/Taste | Rationale |
|----------|-----------|-----------------|-----------|
| Expand scope to include auth | P2 (Boil lakes) | Mechanical | Auth is in blast radius |
| Choose explicit fix over abstraction | P5 (Explicit) | Mechanical | 10-line fix vs 200-line pattern |
| Add loading states | P1 (Completeness) | Taste | Both options viable, completeness preferred |
```

## Important Rules

- **Phases are sequential, never parallel.** Each must complete before the next begins.
- **Auto-decide does NOT mean skip.** Every section at full depth.
- **Taste decisions must be surfaced.** Auto-decide with a recommendation, but the user sees them at the final gate.
- **User Challenges are NEVER auto-decided.** The user's original direction is the default.
- **The final gate is mandatory.** Even if everything was mechanical, present the summary.
- **Read skill files from disk every time.** Never cache — the methodology may have been updated.
