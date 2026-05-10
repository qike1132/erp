# /benchmark — Performance Regression Detection (Comate Adapted)

> Performance baseline + regression detection. API latency, bundle size, database query time, startup time. Compares against previous benchmarks and flags regressions.

Note: Original gstack uses live browser for Lighthouse/Core Web Vitals. This adaptation uses available CLI tools and code analysis.

## Step 1: Define What to Measure

Based on project type, select relevant metrics:

| Project type | Key metrics |
|-------------|-------------|
| Web API | API response time (p50/p95/p99), startup time, memory usage |
| Frontend | Bundle size, page load time, LCP/FID/CLS (if browser available) |
| Database app | Query time, slow queries, connection pool usage |
| CLI tool | Startup time, command execution time |
| Full stack | All of the above |

## Step 2: Establish Baseline

### API Performance
```bash
# Simple latency test (single request)
curl -o /dev/null -s -w "connect:%{time_connect} total:%{time_total}\n" http://localhost:8000/api/v1/health

# Multiple requests for p50/p95/p99
for i in $(seq 1 100); do
  curl -o /dev/null -s -w "%{time_total}\n" http://localhost:8000/api/v1/health
done | sort -n | awk '{a[N]=$1} END {print "p50:", a[int(N*0.5)]; print "p95:", a[int(N*0.95)]; print "p99:", a[int(N*0.99)]}'

# If available, use ab/wrk/k6 for proper load testing
# wrk -t4 -c100 -d30s http://localhost:8000/api/v1/health
```

### Frontend Performance
```bash
# Bundle size
du -sh dist/ 2>/dev/null || du -sh build/ 2>/dev/null || du -sh .next/ 2>/dev/null

# Count and size of JS files
find dist/ -name "*.js" -exec du -b {} + 2>/dev/null | sort -rn | head -10

# Total JS size
find dist/ -name "*.js" -exec cat {} + 2>/dev/null | wc -c

# CSS size
find dist/ -name "*.css" -exec cat {} + 2>/dev/null | wc -c
```

### Database Performance
```sql
-- Check slow queries (PostgreSQL)
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;

-- Check index usage
SELECT schemaname, tablename, indexname, idx_scan
FROM pg_stat_user_indexes
ORDER BY idx_scan ASC
LIMIT 10;

-- Check table sizes
SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 10;
```

### Startup Time
```bash
# Measure cold start time
time (your-start-command)

# For Node.js
time node index.js &
sleep 2 && curl -s http://localhost:8000/health && kill $!
```

## Step 3: Compare Against Baseline

If a previous benchmark exists (`.gstack/benchmarks/`), load and compare:

```
## Performance Comparison

| Metric | Baseline | Current | Change | Status |
|--------|----------|---------|--------|--------|
| API p50 (ms) | 45 | 48 | +6.7% | ✅ |
| API p95 (ms) | 120 | 145 | +20.8% | ⚠️ REGRESSION |
| API p99 (ms) | 250 | 280 | +12.0% | ⚠️ |
| Bundle size (KB) | 340 | 320 | -5.9% | ✅ Improved |
| JS file count | 12 | 14 | +16.7% | ⚠️ |
| DB slow queries | 2 | 5 | +150% | ❌ REGRESSION |
| Startup time (ms) | 800 | 780 | -2.5% | ✅ |
| Memory (MB) | 256 | 264 | +3.1% | ✅ |
```

## Step 4: Regression Rules

Flag as regression if:

| Metric | Regression threshold | Severity |
|--------|---------------------|----------|
| API p50 | > 30% increase | HIGH |
| API p95 | > 20% increase | HIGH |
| API p99 | > 25% increase | MEDIUM |
| Bundle size | > 10% increase | MEDIUM |
| New slow queries | Any new query > 100ms | HIGH |
| Memory usage | > 15% increase | MEDIUM |
| Startup time | > 10% increase | MEDIUM |
| JS file count | > 20% increase | LOW |

**Critical regression** (must fix before shipping):
- API p95 increased > 20%
- Any new slow queries appeared
- Bundle size increased > 15%

**Warning regression** (should investigate):
- API p99 increased > 25%
- Memory usage increased > 15%
- Startup time increased > 10%

## Step 5: Code-Level Analysis

For each regression, identify the code cause:

- **API latency** → check recent commits touching the endpoint, look for N+1 queries, missing indexes, added middleware
- **Bundle size** → check for new large dependencies, missing tree-shaking, duplicated packages
- **Slow queries** → check for new queries without indexes, table scans, missing eager loading
- **Memory** → check for memory leaks (event listeners, closures, caches), large in-memory data
- **Startup** → check for synchronous initialization, large imports at module level

## Step 6: Save Benchmark

Save to `.gstack/benchmarks/{YYYY-MM-DD}.json`:
```json
{
  "date": "2026-05-10",
  "commit": "abc1234",
  "branch": "feature/payments",
  "metrics": {
    "api_p50_ms": 48,
    "api_p95_ms": 145,
    "api_p99_ms": 280,
    "bundle_size_kb": 320,
    "js_file_count": 14,
    "css_size_kb": 45,
    "startup_time_ms": 780,
    "memory_mb": 264,
    "slow_queries": 5,
    "test_count": 142,
    "test_pass_rate": 1.0
  },
  "regressions": [
    {"metric": "api_p95_ms", "baseline": 120, "current": 145, "change_pct": 20.8, "severity": "HIGH"}
  ]
}
```

## Step 7: Report

```
## Benchmark Report

**Date:** 2026-05-10
**Commit:** abc1234
**Branch:** feature/payments

### Summary
- Regressions: 2 (1 HIGH, 1 MEDIUM)
- Improvements: 2
- Stable: 4

### Regressions (must fix or justify)
1. [HIGH] API p95: 120ms → 145ms (+20.8%) — likely caused by N+1 in order listing
2. [MEDIUM] DB slow queries: 2 → 5 (+150%) — new queries without indexes

### Improvements
1. Bundle size: 340KB → 320KB (-5.9%) — tree-shaking optimization
2. Startup time: 800ms → 780ms (-2.5%) — lazy module loading

### Code-Level Findings
1. src/api/orders.ts:45 — N+1 query in list endpoint
2. migration_20260508.sql — missing index on orders.customer_id
```

## Important Rules

- **Always compare against a baseline.** A single measurement is a data point, not a benchmark.
- **Regressions must have code-level explanations.** "It's slower" is not acceptable — find the commit and codepath that caused it.
- **Critical regressions block shipping.** If API p95 regressed > 20%, the feature should not ship without justification.
- **Save every benchmark.** Historical data enables trend analysis.
- **Measure what matters.** Don't benchmark endpoints nobody uses.
