# /benchmark — Performance Regression Detection (Comate Adapted)

> Performance baseline + regression detection. Page load, Core Web Vitals, API latency.

Note: Original gstack uses live browser for Lighthouse/Core Web Vitals. This adaptation uses available tools.

## Step 1: Define Benchmarks

What to measure:
- **Page load time** (if applicable)
- **API response time** (p50, p95, p99)
- **Bundle size** (frontend)
- **Database query time**
- **Memory usage**
- **Startup time** (backend)

## Step 2: Establish Baseline

### API Performance
```bash
# Simple latency test
curl -o /dev/null -s -w "connect:%{time_connect} total:%{time_total}\n" http://localhost:8000/api/v1/health

# If available, use ab/wrk/k6 for load testing
```

### Frontend Performance
```bash
# Bundle size
du -sh dist/ 2>/dev/null || du -sh build/ 2>/dev/null || du -sh .next/ 2>/dev/null

# Count of JS files
find dist/ -name "*.js" | wc -l
```

### Database Performance
```sql
-- Check slow queries (PostgreSQL)
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;
```

## Step 3: Compare Against Baseline

If a previous benchmark exists (`.gstack/benchmarks/`), compare:

```
## Performance Comparison

| Metric | Baseline | Current | Change |
|--------|----------|---------|--------|
| API p95 (ms) | 120 | 145 | +20.8% ⚠️ |
| Bundle size (KB) | 340 | 320 | -5.9% ✅ |
| DB slow queries | 2 | 5 | +150% ❌ |
| Startup time (ms) | 800 | 780 | -2.5% ✅ |
```

## Step 4: Regression Rules

Flag as regression if:
- API p95 increased > 20%
- Bundle size increased > 10%
- Any new slow queries appeared
- Memory usage increased > 15%
- Startup time increased > 10%

## Step 5: Save Benchmark

Save to `.gstack/benchmarks/{YYYY-MM-DD}.json`:
```json
{
  "date": "2026-05-10",
  "commit": "abc1234",
  "metrics": {
    "api_p95_ms": 145,
    "bundle_size_kb": 320,
    "startup_time_ms": 780,
    "slow_queries": 5
  }
}
```

## Proactive Trigger Rules

Invoke this skill when:
- User asks about performance
- Before/after a significant change
- User says "benchmark" or "performance regression"
