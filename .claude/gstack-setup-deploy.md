# /setup-deploy — Configure Deployment Settings (Comate Adapted)

> Configure deployment settings for /land-and-deploy. Detects your deploy platform, production URL, health check endpoints, and deploy status commands. Writes the configuration to CLAUDE.md so all future deploys are automatic.

## Step 1: Platform Detection

Scan the project for deployment platform indicators:

| Indicator | Platform |
|-----------|----------|
| `fly.toml` / `Dockerfile` + fly.io in docs | Fly.io |
| `render.yaml` / `render.com` in docs | Render |
| `vercel.json` / `next.config.*` / `.vercel/` | Vercel |
| `netlify.toml` / `_redirects` / `.netlify/` | Netlify |
| `Procfile` / `app.json` / `heroku` in docs | Heroku |
| `.github/workflows/deploy*.yml` | GitHub Actions |
| `docker-compose.yml` / `Dockerfile` | Custom Docker |
| `k8s/` / `*.yaml` with apiVersion: apps/v1 | Kubernetes |
| `terraform/` / `*.tf` | Terraform/IaC |
| `Dockerfile` + `docker-compose*.yml` | Docker Compose |
| None of the above | Ask user |

If multiple indicators found, present options and ask which is the primary deployment target.

## Step 2: Gather Configuration

For the detected platform, gather:

### Common (all platforms)
- **Production URL** — the live URL users access
- **Health check endpoint** — URL that returns 200 when healthy
- **Deploy command** — how to trigger a deployment
- **Deploy status command** — how to check if deployment succeeded

### Platform-specific

**Fly.io:**
- App name: from `fly.toml`
- Region: from `fly.toml` or ask
- Deploy command: `fly deploy`
- Status command: `fly status`

**Render:**
- Service ID: from `render.yaml` or dashboard
- Deploy command: `render deploy` or git push
- Status command: `render status` or API

**Vercel:**
- Project name: from `vercel.json` or dashboard
- Deploy command: `vercel --prod`
- Status command: `vercel ls`

**Netlify:**
- Site name: from `netlify.toml` or dashboard
- Deploy command: `netlify deploy --prod`
- Status command: `netlify status`

**GitHub Actions:**
- Workflow file: `.github/workflows/deploy*.yml`
- Trigger: push to main, manual dispatch, etc.
- Status command: `gh run list --workflow=deploy.yml`

**Heroku:**
- App name: from `app.json` or `heroku apps:info`
- Deploy command: `git push heroku main`
- Status command: `heroku ps`

**Custom Docker:**
- Container name or compose service
- Deploy command: `docker compose up -d` or custom script
- Status command: `docker compose ps` or health check

**Kubernetes:**
- Namespace, deployment name
- Deploy command: `kubectl apply -f k8s/`
- Status command: `kubectl rollout status deployment/<name>`

## Step 3: Health Check Configuration

Identify or configure a health check endpoint:

1. **Check for existing health endpoint** — `/health`, `/api/health`, `/api/v1/health`, `/status`
2. **If none exists:** recommend adding one (simple endpoint that returns 200 + basic status info)
3. **Configure expected response** — status code, response body shape, acceptable latency

Recommended health check response:
```json
{
  "status": "ok",
  "version": "1.2.3",
  "uptime_seconds": 86400
}
```

## Step 4: Deploy Verification Commands

Configure how to verify a deployment succeeded:

```bash
# Basic — HTTP status check
curl -s -o /dev/null -w "%{http_code}" https://your-app.com/health

# Detailed — check response and latency
curl -s -w "\nHTTP %{http_code} Time: %{time_total}s\n" https://your-app.com/health

# Platform-specific — check deployment status
fly status  # Fly.io
heroku ps   # Heroku
gh run list --limit 1  # GitHub Actions
```

## Step 5: Write Configuration

Add a deployment configuration section to CLAUDE.md:

```markdown
## Deployment Configuration

### Platform
- **Platform:** <Fly.io/Render/Vercel/Heroku/GitHub Actions/Docker/K8s/Custom>
- **App name:** <name>
- **Region:** <region> (if applicable)

### URLs
- **Production:** https://your-app.com
- **Staging:** https://staging.your-app.com (if applicable)
- **Health check:** https://your-app.com/health

### Commands
- **Deploy:** <deploy-command>
- **Status:** <status-command>
- **Rollback:** <rollback-command>
- **Logs:** <logs-command>

### Verification
- **Health check endpoint:** GET /health → 200 OK
- **Key endpoint:** GET /api/v1/status → 200 OK
- **Max deploy time:** 5 minutes
- **Rollback if health check fails for:** 2 consecutive checks

### CI/CD
- **Pipeline:** <GitHub Actions/GitLab CI/etc.>
- **Workflow file:** .github/workflows/deploy.yml
- **Trigger:** Push to main branch
```

## Step 6: Verify Configuration

Test the configuration by running:

1. **Health check** — verify the endpoint returns 200
2. **Status command** — verify it shows current deployment info
3. **Logs command** — verify it shows recent logs

If any command fails, note it and suggest fixes.

## Important Rules

- **Never guess platform settings.** If detection is ambiguous, ask the user.
- **Health check endpoint is mandatory.** Without it, /land-and-deploy can't verify deployments.
- **Include rollback command.** Every deployment should have a documented rollback procedure.
- **Write to CLAUDE.md, not a separate file.** This keeps deployment config alongside project context.
- **Test the configuration.** Don't just write it — verify the commands work.
