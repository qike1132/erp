# /cso — Chief Security Officer Audit (Comate Adapted)

> OWASP Top 10 + STRIDE threat modeling. Two modes: daily (8/10 confidence) or comprehensive (2/10 bar).

## Mode Selection

- **Daily** — Quick scan, 8/10 confidence gate, zero noise. Focus on CRITICAL/HIGH only.
- **Comprehensive** — Deep scan, 2/10 bar, full coverage. All severity levels.

Default to daily unless user specifies comprehensive.

## Phase 0: Architecture Mental Model + Stack Detection

1. Scan project structure for tech stack indicators:
   - `package.json` → Node.js/JS framework
   - `requirements.txt` / `pyproject.toml` → Python
   - `go.mod` → Go
   - `Dockerfile` → containerized
   - `*.tf` / `*.pulumi.ts` → IaC
2. Build mental model of: entry points, data flow, authentication, storage
3. Identify trust boundaries (where untrusted input enters the system)

## Phase 1: Attack Surface Census

**Code Surface:**
- API endpoints (public + internal)
- WebSocket handlers
- File upload/download endpoints
- Admin panels
- Webhook receivers
- Background job processors

**Infrastructure Surface:**
- Exposed ports
- Public S3 buckets
- Database access patterns
- CDN configurations

## Phase 2: Secrets Archaeology

Search for leaked secrets:
```bash
# Check .env files
find . -name ".env*" -not -path "*/node_modules/*" -not -path "*/.git/*"

# Check git history for accidentally committed secrets
git log --all --diff-filter=A --name-only --pretty=format: -- "*.env" "*.key" "*.pem" "*secret*" "*credential*"

# Check CI configs for hardcoded secrets
grep -r "password\|secret\|api_key\|token\|credential" --include="*.yml" --include="*.yaml" .github/ .gitlab-ci.yml
```

**Red flags:**
- Hardcoded API keys, passwords, tokens
- `.env` files committed to git
- Secrets in CI/CD configs without using secret stores
- Private keys in source code

## Phase 3: Dependency Supply Chain

```bash
# Check for known vulnerabilities
npm audit    # Node.js
pip audit    # Python
cargo audit  # Rust
```

- Check lockfile integrity (package-lock.json, poetry.lock)
- Review install scripts (postinstall, preinstall)
- Check for deprecated/abandoned dependencies

## Phase 4: CI/CD Pipeline Security

- Unpinned GitHub Actions (use SHA, not tags)
- `pull_request_target` with checkout of PR head
- Script injection via untrusted PR data
- Self-hosted runner security
- Missing branch protection rules

## Phase 5: Webhook & Integration Audit

- Signature verification on incoming webhooks
- TLS verification enabled for outgoing requests
- Idempotency for webhook handlers
- Rate limiting on webhook endpoints

## Phase 6: LLM & AI Security

If the project uses LLM/AI:
- Prompt injection vectors (user input in system prompts)
- Unsanitized LLM output used for commands/queries
- Tool call validation (LLM choosing which tools to call)
- Data exfiltration via prompt manipulation

## Phase 7: OWASP Top 10 Assessment

| ID | Category | Quick Check |
|----|----------|-------------|
| A01 | Broken Access Control | Are endpoints properly auth'd? Can users access other users' data? |
| A02 | Cryptographic Failures | Is sensitive data encrypted at rest and in transit? |
| A03 | Injection | SQL injection, XSS, command injection, LDAP injection |
| A04 | Insecure Design | Missing rate limits, no threat modeling, trust boundaries unclear |
| A05 | Security Misconfiguration | Default credentials, unnecessary features enabled, verbose errors |
| A06 | Vulnerable Components | Outdated dependencies with known CVEs |
| A07 | Auth Failures | Weak passwords, no MFA, session management issues |
| A08 | Data Integrity Failures | Untrusted deserialization, no integrity checks on updates |
| A09 | Logging Failures | Missing audit logs, sensitive data in logs, no breach detection |
| A10 | SSRF | Can users make the server fetch arbitrary URLs? |

## Phase 8: STRIDE Threat Model

| Threat | What to check |
|--------|--------------|
| **S**poofing | Authentication bypass, session hijacking, MFA gaps |
| **T**ampering | Input validation, integrity checks, HMAC signatures |
| **R**epudiation | Audit logs, non-repudiation, action attribution |
| **I**nformation Disclosure | Data classification, access controls, error messages |
| **D**enial of Service | Rate limiting, resource quotas, input size limits |
| **E**levation of Privilege | RBAC enforcement, privilege escalation paths |

## Phase 9: Findings Report

```
## Security Audit Report

**Mode:** daily / comprehensive
**Date:** YYYY-MM-DD
**Scope:** [what was scanned]

### Attack Surface Summary
| Surface type | Count |
|-------------|-------|
| API endpoints | N |
| Webhook receivers | N |
| ... | ... |

### Findings

| # | Severity | Confidence | Category | File:Line | Description | Status |
|---|----------|-----------|----------|-----------|-------------|--------|
| 1 | CRITICAL | VERIFIED | A03 | src/api.ts:42 | SQL injection via string concat | UNFIXED |

### Critical Path
1. Most urgent finding and why
2. Second most urgent
3. ...

### Remediation Priority
1. [Immediate] Fix description
2. [This week] Fix description
3. [This sprint] Fix description
```

## Proactive Trigger Rules

Invoke this skill when:
- User asks for security audit
- User mentions "OWASP", "STRIDE", "security review"
- Before deploying a new service or API
- After adding authentication or authorization features
