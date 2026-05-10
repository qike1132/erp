# /ship — Release Engineering (Comate Adapted)

> Run tests, review, push, open PR. Workspace-aware version queue.

## Step 0: Platform Detection

Detect the platform and base branch:
```bash
# Detect GitHub vs GitLab
gh repo view 2>/dev/null && echo "GITHUB" || (glab repo view 2>/dev/null && echo "GITLAB" || echo "UNKNOWN")

# Detect base branch
git remote show origin 2>/dev/null | grep "HEAD branch" | awk '{print $NF}'
# Or fallback: main, master, develop
```

## Step 1: Pre-flight Checks

1. **Clean working tree?** `git status --porcelain`
   - If dirty: ask user — commit changes first, stash, or abort?
2. **On feature branch?** Not main/master
   - If on main: create a feature branch first
3. **Base branch up to date?**
   ```bash
   git fetch origin main
   git log HEAD..origin/main --oneline
   ```
   - If behind: merge or rebase from base FIRST (prevents integration surprises)

## Step 2: Run Tests

```bash
# Detect test command from package.json / Makefile / pyproject.toml
# Run the appropriate test suite
```

If tests fail:
- Report the failures
- Ask: fix now, or ship anyway with known failures?

## Step 3: Review

Run the `/review` skill methodology:
1. Read full diff against base branch
2. Check for structural issues (SQL injection, trust boundary violations, race conditions)
3. Verify validators exist and are called
4. Output findings with severity markers

If BLOCKER issues found:
- Report and ask: fix before shipping, or acknowledge and ship?

## Step 4: VERSION Bump

If a VERSION file exists:
```bash
# Read current version
cat VERSION
# Bump according to changes (major/minor/patch)
# Write new version
echo "1.2.0" > VERSION
```

Convention:
- **Major** (X.0.0): Breaking API changes
- **Minor** (0.X.0): New features, backwards-compatible
- **Patch** (0.0.X): Bug fixes, no new features

If no VERSION file, skip this step.

## Step 5: CHANGELOG Update

Append to CHANGELOG.md:
```markdown
## [VERSION] - YYYY-MM-DD

### Added
- Feature description

### Changed
- Change description

### Fixed
- Fix description

### Breaking
- Breaking change description (if major)
```

## Step 6: Commit & Push

```bash
git add -A
git commit -m "v<VERSION>: <summary of changes>"
git push -u origin HEAD
```

## Step 7: Create PR

```bash
# GitHub
gh pr create --title "v<VERSION>: <summary>" --body "$(cat <<'EOF'
## Changes

- Change 1
- Change 2

## Test plan

- [ ] Test 1
- [ ] Test 2
EOF
)"

# GitLab
glab mr create --title "v<VERSION>: <summary>" --description "..."
```

## Post-ship Checklist

- [ ] CI passes on the PR
- [ ] At least one review approved
- [ ] No merge conflicts
- [ ] CHANGELOG is updated
- [ ] VERSION is bumped (if applicable)

## Proactive Trigger Rules

Invoke this skill when:
- User says "ship it", "deploy", "create a PR"
- User says code is ready
- User asks about deploying or pushing code
