# /health — Code Quality Dashboard (Comate Adapted)

> Quick health check: type checker, linter, tests, dead code, dependencies.

## Step 1: Detect Project Type

Scan for:
- `package.json` → Node.js/TypeScript
- `pyproject.toml` / `requirements.txt` → Python
- `go.mod` → Go
- `Cargo.toml` → Rust

## Step 2: Run Checks

### Type Checker
```bash
# TypeScript
npx tsc --noEmit 2>&1 | tail -1

# Python
mypy . --ignore-missing-imports 2>&1 | tail -5
```

### Linter
```bash
# JavaScript/TypeScript
npx eslint . --format compact 2>&1 | wc -l

# Python
ruff check . 2>&1 | wc -l
```

### Tests
```bash
# Run test suite and capture results
npm test 2>&1 | tail -5
# Or pytest, go test, cargo test, etc.
```

### Dead Code
```bash
# Find unused exports (TypeScript)
npx ts-prune 2>&1 | grep -v "used in module" | wc -l

# Find potentially unused files
# Check imports across the codebase
```

### Dependencies
```bash
# Outdated dependencies
npm outdated 2>&1 | wc -l

# Vulnerable dependencies
npm audit 2>&1 | grep -c "vulnerability"
```

## Step 3: Health Score

Calculate a 0-100 score:

| Factor | Weight | Scoring |
|--------|--------|---------|
| Type errors | 25 | 0 errors = 25, else max(0, 25 - errors*2) |
| Lint warnings | 20 | 0 warnings = 20, else max(0, 20 - warnings*0.5) |
| Test pass rate | 25 | 100% pass = 25, else proportional |
| Test coverage | 15 | >80% = 15, >60% = 10, >40% = 5, else 0 |
| Dead code | 10 | 0 unused = 10, else max(0, 10 - count) |
| Dependency health | 5 | 0 vulnerabilities = 5, else max(0, 5 - vulns) |

## Step 4: Output Dashboard

```
## Code Health Dashboard

**Overall Score: 78/100** 🟡

| Category | Status | Details |
|----------|--------|---------|
| Type Checker | ✅ Clean | 0 errors |
| Linter | ⚠️ 12 warnings | Mostly unused vars |
| Tests | ✅ 142/142 passing | Coverage: 72% |
| Dead Code | ⚠️ 3 unused exports | src/utils.ts:exportX |
| Dependencies | ❌ 2 vulnerabilities | lodash@4.17.20 (prototype pollution) |

### Top Recommendations
1. [Most impactful improvement]
2. [Second most impactful]
3. [Third]
```

## Proactive Trigger Rules

Invoke this skill when:
- User asks "how's the codebase doing?"
- User wants a quick health check
- User asks about technical debt
