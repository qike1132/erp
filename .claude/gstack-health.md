# /health — Code Quality Dashboard (Comate Adapted)

> Quick health check: type checker, linter, tests, dead code, dependencies. Computes a weighted composite 0-10 score and tracks trends over time.

## Step 1: Detect Project Type

Scan for:
- `package.json` → Node.js/TypeScript
- `pyproject.toml` / `requirements.txt` → Python
- `go.mod` → Go
- `Cargo.toml` → Rust
- `composer.json` → PHP

## Step 2: Run Wrapped Tools

Run each check and capture results. Adapt commands to the detected project type.

### Type Checker
```
# TypeScript
npx tsc --noEmit 2>&1 | tail -1

# Python (mypy)
mypy . --ignore-missing-imports 2>&1 | tail -5

# Go
go vet ./...

# Rust
cargo check 2>&1 | tail -5
```

### Linter
```
# JavaScript/TypeScript
npx eslint . --format compact 2>&1 | wc -l

# Python (ruff)
ruff check . 2>&1 | wc -l

# Go
golangci-lint run ./... 2>&1 | wc -l

# Rust
cargo clippy 2>&1 | tail -10
```

### Tests
```
# Run test suite and capture results
npm test 2>&1 | tail -5
# Or: pytest, go test, cargo test, phpunit, etc.

# Capture: total tests, passed, failed, skipped
```

### Dead Code
```
# Find unused exports (TypeScript)
npx ts-prune 2>&1 | grep -v "used in module" | wc -l

# Find potentially unused files
# Check imports across the codebase

# Python
# Check for unused imports: ruff check --select F401
```

### Dependencies
```
# Outdated dependencies
npm outdated 2>&1 | wc -l

# Vulnerable dependencies
npm audit 2>&1 | grep -c "vulnerability"

# Python
pip audit 2>&1 | wc -l
```

### Shell Lint (if applicable)
```
# shellcheck
shellcheck **/*.sh 2>&1 | wc -l
```

## Step 3: Composite Score (0-10)

Calculate a weighted composite score:

| Factor | Weight | Scoring |
|--------|--------|---------|
| Type errors | 2.5 | 0 errors = 2.5, else max(0, 2.5 - errors×0.2) |
| Lint warnings | 2.0 | 0 warnings = 2.0, else max(0, 2.0 - warnings×0.05) |
| Test pass rate | 2.5 | 100% pass = 2.5, else proportional |
| Test coverage | 1.5 | >80% = 1.5, >60% = 1.0, >40% = 0.5, else 0 |
| Dead code | 1.0 | 0 unused = 1.0, else max(0, 1.0 - count×0.1) |
| Dependency health | 0.5 | 0 vulnerabilities = 0.5, else max(0, 0.5 - vulns×0.1) |

**Total: 0-10 scale**

| Score | Rating | Color |
|-------|--------|-------|
| 9-10 | Excellent | Green |
| 7-8.9 | Good | Light green |
| 5-6.9 | Fair | Yellow |
| 3-4.9 | Poor | Orange |
| 0-2.9 | Critical | Red |

## Step 4: Trend Tracking

Save each health check to `.gstack/health/YYYY-MM-DD.json`:
```json
{
  "date": "2026-05-10",
  "commit": "abc1234",
  "score": 7.8,
  "breakdown": {
    "type_errors": 0,
    "lint_warnings": 12,
    "test_pass_rate": 1.0,
    "test_coverage": 0.72,
    "dead_code": 3,
    "vulnerabilities": 1
  }
}
```

Compare with previous runs:
```
### Trend (Last 4 Checks)
| Date | Score | Type | Lint | Tests | Coverage | Dead | Deps |
|------|-------|------|------|-------|----------|------|------|
| 05-03 | 7.2 | ✅ | ⚠️ 15 | ✅ | 68% | 5 | ❌ 2 |
| 05-05 | 7.5 | ✅ | ⚠️ 14 | ✅ | 70% | 4 | ❌ 1 |
| 05-08 | 7.6 | ✅ | ⚠️ 13 | ✅ | 71% | 3 | ✅ 0 |
| 05-10 | 7.8 | ✅ | ⚠️ 12 | ✅ | 72% | 3 | ❌ 1 |
```

## Step 5: Output Dashboard

```
## Code Health Dashboard

**Overall Score: 7.8/10** 🟡 Good

| Category | Status | Details |
|----------|--------|---------|
| Type Checker | ✅ Clean | 0 errors |
| Linter | ⚠️ 12 warnings | Mostly unused vars (6), missing return types (4), any types (2) |
| Tests | ✅ 142/142 passing | Coverage: 72% |
| Dead Code | ⚠️ 3 unused exports | src/utils.ts:exportX, src/types.ts:OldInterface, src/api.ts:deprecatedFn |
| Dependencies | ❌ 1 vulnerability | lodash@4.17.20 (prototype pollution) — update to 4.17.21 |

### Top Recommendations (by impact on score)
1. Fix linter warnings (+0.6 potential) — start with unused vars and any types
2. Increase test coverage from 72% to 80% (+0.5 potential) — focus on src/api.ts
3. Remove dead code (+0.3 potential) — 3 unused exports found
4. Update lodash (+0.1 potential) — 1 known vulnerability

### Trend
↑ Score improved from 7.2 → 7.8 over last 7 days
↑ Coverage improved from 68% → 72%
↓ Lint warnings decreased from 15 → 12
```

## Important Rules

- **Run all checks, not just some.** A partial health check gives a misleading score.
- **The composite score is weighted by impact.** Type errors and test failures matter more than lint warnings.
- **Trends matter more than snapshots.** A 7.8 that was 7.2 last week is better than a 8.0 that was 9.0.
- **Recommendations must be specific.** Not "fix lint" but "remove 6 unused variables in src/utils.ts".
- **Save results for trend tracking.** Without history, there's no trend.
