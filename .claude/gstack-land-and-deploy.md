# /land-and-deploy — Merge PR + Deploy + Verify (Comate Adapted)

> Merge the PR, wait for CI and deploy, verify production health. Takes over after /ship creates the PR.

## Step 1: Pre-merge Checklist

Verify before merging:

- [ ] PR has at least one approval (if team setting)
- [ ] CI is passing (green check)
- [ ] No merge conflicts
- [ ] CHANGELOG is updated
- [ ] Version bump is correct (if applicable)
- [ ] No unresolved review comments
- [ ] Branch is up to date with base branch

If any item fails, **stop and report.** Don't merge a failing PR.

## Step 2: Merge

```bash
# GitHub (prefer squash merge for clean history)
gh pr merge <PR-NUMBER> --squash --delete-branch

# GitLab
glab mr merge <MR-NUMBER> --squash --remove-source-branch

# Manual
git checkout main
git merge --squash feature/branch
git commit -m "feat: description (#PR-NUMBER)"
git push origin main
```

**Merge strategy:**
- Default: squash merge (keeps main history clean)
- If PR has carefully structured commits: merge commit (preserves history)
- Never: rebase merge (rewrites history, confusing for collaborators)

## Step 3: Monitor CI/CD

```bash
# GitHub
gh run list --limit 3
gh run watch <run-id>

# GitLab
glab ci trace

# Generic — poll until done
while true; do
  status=$(curl -s https://api.github.com/repos/OWNER/REPO/actions/runs/<run-id> | jq .status)
  if [ "$status" != '"in_progress"' ]; then break; fi
  sleep 10
done
```

Wait for:
- Build to succeed
- Tests to pass
- Deploy to complete
- Health check to return 200

**Timeout:** If CI doesn't complete within 15 minutes, alert the user. Don't wait indefinitely.

## Step 4: Verify Production Health

### Basic Health Check
```bash
# HTTP status check
curl -s -o /dev/null -w "%{http_code}" https://your-app.com/health

# Full health response
curl -s https://your-app.com/api/v1/health
```

### Key Endpoint Check
```bash
# Test critical endpoints
curl -s -w "\nHTTP %{http_code} Time: %{time_total}s\n" https://your-app.com/api/v1/status
```

### Error Rate Check (if monitoring available)
```bash
# Check for error spikes
# This depends on your monitoring setup
```

### Performance Check
```bash
# Quick latency check
curl -o /dev/null -s -w "total:%{time_total}s\n" https://your-app.com/api/v1/health
```

## Step 5: Post-deploy Verification Checklist

- [ ] Homepage loads (200 status)
- [ ] Login works (test with real credentials if available)
- [ ] Key user flow works (the feature that was shipped)
- [ ] No error spikes in monitoring
- [ ] Response times within normal range
- [ ] No JavaScript console errors (if browser testing available)
- [ ] Database migrations applied correctly
- [ ] External integrations still working

**Verification depth:**
- **Quick** — health check + homepage + key endpoint (1-2 minutes)
- **Standard** — all above + login + key user flow (5 minutes)
- **Thorough** — all above + edge cases + performance comparison (15 minutes)

Default to Standard. Use Quick for hotfixes. Use Thorough for major releases.

## Step 6: Rollback Decision

If verification fails:

1. **Assess severity** — is it a minor issue or a user-facing outage?
2. **Quick fix possible?** — can you fix and redeploy in <15 minutes?
3. **If not: ROLLBACK** — revert the merge and redeploy previous version

```bash
# GitHub revert
gh pr revert <PR-NUMBER>

# Manual revert
git revert <merge-commit-hash>
git push origin main
```

**Never debug in production.** Rollback first, debug in staging.

## Step 7: Report

```
## Deploy Report

**PR:** #<number> — <title>
**Merged:** <timestamp>
**Deployed:** <timestamp>
**CI Duration:** <X> minutes
**Health Check:** ✅ / ❌
**Production URL:** <url>
**Deploy Strategy:** squash-merge

### Verification
- [x] Homepage loads
- [x] Login works
- [x] Key flow works
- [ ] Error rate within bounds — ⚠️ slight increase, monitoring
- [x] Response times normal

### Performance
- Health endpoint: 48ms (baseline: 45ms, +6.7% ✅)
- Key API endpoint: 120ms (baseline: 115ms, +4.3% ✅)

### Action Items
- <any issues found during verification>
- <monitoring recommendations>

### Rollback Plan (if needed)
- Revert commit: <hash>
- Previous deploy: <version>
```

## Important Rules

- **Never merge a failing PR.** If CI is red, stop.
- **Always verify after deploy.** A successful deploy doesn't mean a successful release.
- **Rollback first, debug second.** Production issues get resolved by rollback, not hotfixing.
- **Set a timeout.** If CI takes >15 minutes, alert the user. Don't wait forever.
- **Delete source branches after merge.** Keeps the branch list clean.
