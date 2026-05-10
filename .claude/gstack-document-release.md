# /document-release — Update Docs After Shipping (Comate Adapted)

> Update all docs to match what you just shipped.

## Step 1: Detect What Shipped

```bash
# Latest tag or commit
git log --oneline -1

# Diff since last release
git log <last-tag>..HEAD --oneline

# Files changed
git diff <last-tag>..HEAD --name-only
```

## Step 2: Documentation Inventory

Find all documentation files that may need updates:

```bash
# Find docs
find . -name "README*" -o -name "CHANGELOG*" -o -name "*.md" -path "*/docs/*" | grep -v node_modules | grep -v .git
```

Check:
- [ ] README.md — version numbers, install instructions, feature list
- [ ] CHANGELOG.md — new version entry
- [ ] API documentation — new/changed endpoints
- [ ] Configuration docs — new config options
- [ ] Getting started guide — changed steps
- [ ] Migration guide — breaking changes
- [ ] Environment variables — new required vars
- [ ] Contributing guide — changed dev setup
- [ ] Architecture docs — changed system design
- [ ] Type definitions — new/changed types

## Step 3: Update Each Doc

For each doc that needs updating:

1. **Read the current content**
2. **Identify what changed** based on the diff
3. **Update with specific changes**:
   - New features: add to feature list, add usage examples
   - Breaking changes: add migration instructions
   - Bug fixes: note in changelog
   - Config changes: update env var tables
   - API changes: update endpoint docs

## Step 4: Changelog Entry

```markdown
## [VERSION] - YYYY-MM-DD

### Added
- Feature description (#PR)

### Changed
- Change description (#PR)

### Deprecated
- What's being deprecated, removal timeline

### Removed
- What was removed, migration path

### Fixed
- Bug fix description (#PR)

### Security
- Security fix description (#PR)
```

## Step 5: Verify

- [ ] All version references updated
- [ ] Code examples still work
- [ ] Links still valid
- [ ] No references to removed features
- [ ] New features have documentation

## Proactive Trigger Rules

Invoke this skill when:
- After shipping a new version
- User says "update the docs"
- After merging a significant feature
