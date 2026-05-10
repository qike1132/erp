# /document-release — Update Docs After Shipping (Comate Adapted)

> Post-ship documentation update. Reads all project docs, cross-references the diff, updates README/ARCHITECTURE/CONTRIBUTING/CLAUDE.md to match what shipped. Polishes CHANGELOG voice, cleans up TODOS, and optionally bumps VERSION.

## Step 1: Detect What Shipped

```
# Latest tag or commit
git log --oneline -1

# Diff since last release
git log <last-tag>..HEAD --oneline

# Files changed since last release
git diff <last-tag>..HEAD --name-only

# Full diff stat
git diff <last-tag>..HEAD --stat

# Commit types breakdown
git log <last-tag>..HEAD --oneline | grep -c "feat"
git log <last-tag>..HEAD --oneline | grep -c "fix"
git log <last-tag>..HEAD --oneline | grep -c "breaking"
```

## Step 2: Documentation Inventory

Find all documentation files that may need updates:

```
# Find docs
find . -name "README*" -o -name "CHANGELOG*" -o -name "*.md" -path "*/docs/*" | grep -v node_modules | grep -v .git
```

Check each for relevance:

| Doc | When to update | What to check |
|-----|---------------|---------------|
| README.md | Always | Version numbers, install instructions, feature list, requirements |
| CHANGELOG.md | Always | New version entry with all changes |
| API documentation | If API changed | New/changed/removed endpoints, request/response shapes |
| Configuration docs | If config changed | New config options, changed defaults, removed options |
| Getting started guide | If setup changed | Changed steps, new prerequisites, updated commands |
| Migration guide | If breaking changes | Upgrade steps, data migration, config changes |
| Environment variables | If env vars changed | New required vars, changed defaults, removed vars |
| Contributing guide | If dev setup changed | Updated dev commands, new test requirements |
| Architecture docs | If architecture changed | New services, changed dependencies, data flow changes |
| Type definitions | If types changed | New/changed/removed types, breaking type changes |
| CLAUDE.md | Always | Project context, conventions, patterns that AI should know |
| TODOS.md | Always | Remove completed items, add discovered items |

## Step 3: Cross-Reference Diff with Docs

For each file in the diff, identify which docs should mention it:

```
| Changed file | Doc impact | Action needed |
|-------------|-----------|---------------|
| src/api/orders.ts | API docs, README | Add new /orders endpoint docs |
| .env.example | Config docs, README | Add new ORDER_SERVICE_URL var |
| migrations/004.sql | Migration guide | Add migration step for new table |
| src/types.ts | Type definitions | Document new OrderStatus enum |
```

## Step 4: Update Each Doc

For each doc that needs updating:

1. **Read the current content** — understand what's there
2. **Identify what changed** — based on the diff cross-reference
3. **Update with specific changes:**
   - New features: add to feature list, add usage examples
   - Breaking changes: add migration instructions with before/after
   - Bug fixes: note in changelog with affected versions
   - Config changes: update env var tables, add new vars
   - API changes: update endpoint docs with new request/response shapes
   - Architecture changes: update diagrams, dependency lists

### Voice Rules for Updates
- **README/Getting Started:** Clear, concise, imperative ("Run `npm start`" not "You can run npm start if you want")
- **CHANGELOG:** Factual, specific, version-linked ("Fixed memory leak in order processing (#123)" not "Fixed some bugs")
- **Migration Guide:** Step-by-step, copy-paste friendly, with before/after examples
- **API Docs:** Complete request/response examples, error cases, version info

## Step 5: CHANGELOG Entry

Generate a CHANGELOG entry following Keep a Changelog format:

```markdown
## [VERSION] - YYYY-MM-DD

### Added
- Feature description with context (#PR)
- `NEW_CONFIG_VAR` environment variable for [purpose] (#PR)

### Changed
- Change description with impact (#PR)
- `OLD_CONFIG_VAR` now defaults to [new value] instead of [old value] (#PR)

### Deprecated
- What's being deprecated, removal timeline, migration path (#PR)

### Removed
- What was removed, why, and migration path (#PR)

### Fixed
- Bug fix description with affected behavior (#PR)
- Memory leak in order processing under high load (#PR)

### Security
- Security fix description with CVE if applicable (#PR)
```

**CHANGELOG voice rules:**
- Each entry must reference the PR number
- Each entry must be specific enough to understand without reading the PR
- Group by type (Added/Changed/Deprecated/Removed/Fixed/Security)
- Order within each group: most impactful first

## Step 6: Update TODOS.md

- **Remove completed items** that shipped in this release
- **Add discovered items** from the shipping process
- **Update in-progress items** with current status

## Step 7: Update CLAUDE.md

If CLAUDE.md exists, update the project context section:
- New patterns or conventions established
- Changed architecture decisions
- New dependencies or tools
- Updated project structure

## Step 8: Verify

- [ ] All version references updated (README, package.json, CLAUDE.md)
- [ ] Code examples in docs still work (copy-paste test)
- [ ] Links still valid (no 404s)
- [ ] No references to removed features
- [ ] New features have documentation
- [ ] Breaking changes have migration instructions
- [ ] CHANGELOG entry is complete and accurate
- [ ] TODOS.md is up to date

## Important Rules

- **Every changed file must be accounted for.** If a file changed and no doc mentions it, either the doc is missing or the change is undocumented.
- **CHANGELOG entries must reference PRs.** A changelog without PR numbers is unverifiable.
- **Migration guides for breaking changes are mandatory.** A breaking change without a migration path is user-hostile.
- **Verify code examples.** A code example that doesn't work is worse than no example.
- **Don't just add — also remove.** If a feature was removed, remove its docs too. Stale docs are worse than missing docs.
