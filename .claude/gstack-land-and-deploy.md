# /land-and-deploy — Merge PR + Deploy + Verify (Comate Adapted)

> Merge the PR, wait for CI and deploy, verify production health.

## Step 1: Pre-merge Checklist

- [ ] PR has at least one approval
- [ ] CI is passing (green)
- [ ] No merge conflicts
- [ ] CHANGELOG is updated
- [ ] Version bump is correct (if applicable)
- [ ] No unresolved review comments

## Step 2: Merge

```bash
# GitHub
gh pr merge <PR-NUMBER> --squash --delete-branch

# GitLab
glab mr merge <MR-NUMBER> --squash --remove-source-branch
```

Prefer squash merge to keep history clean.

## Step 3: Monitor CI/CD

```bash
# Watch the deployment pipeline
gh run list --limit 3
gh run watch <run-id>
```

Wait for:
- Build to succeed
- Tests to pass
- Deploy to complete
- Health check to return 200

## Step 4: Verify Production Health

```bash
# Basic health check
curl -s -o /dev/null -w "%{http_code}" https://your-app.com/health

# Check key endpoints
curl -s https://your-app.com/api/v1/health | python -m json.tool

# Check for error spikes in logs (if accessible)
```

## Step 5: Post-deploy Verification

- [ ] Homepage loads
- [ ] Login works
- [ ] Key user flow works
- [ ] No error spikes in monitoring
- [ ] Response times within normal range

## Step 6: Report

```
## Deploy Report

**PR:** #<number> — <title>
**Merged:** <timestamp>
**Deployed:** <timestamp>
**CI Duration:** <X> minutes
**Health Check:** ✅ / ❌
**Production URL:** <url>

### Verification
- [x] Homepage loads
- [x] Login works
- [x] Key flow works
- [ ] Error rate within bounds

### Action Items
- <any issues found>
```

## Proactive Trigger Rules

Invoke this skill when:
- PR is approved and CI is green
- User says "merge and deploy", "land this PR"
- After `/ship` when PR is ready
