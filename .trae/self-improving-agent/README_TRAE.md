# Self-Improvement Skill for Trae

**Version**: 3.0.1  
**Author**: peterskoett  
**Description**: Captures learnings, errors, and corrections to enable continuous improvement

## Installation in Trae

1. Open Trae IDE
2. Go to Skills panel (技能)
3. Click "创建" (Create) button
4. Copy the content below into the skill editor

## Skill Content

```markdown
# Self-Improvement Skill

## Purpose
Log learnings and errors to markdown files for continuous improvement.

## When to Use

### 1. Command/Operation Fails
→ Log to `.learnings/ERRORS.md`

### 2. User Corrects You
Examples:
- "No, that's not right..."
- "Actually, it should be..."
- "You're wrong about..."
→ Log to `.learnings/LEARNINGS.md` with category `correction`

### 3. User Requests Missing Feature
Examples:
- "Can you also..."
- "I wish you could..."
- "Why can't you..."
→ Log to `.learnings/FEATURE_REQUESTS.md`

### 4. Knowledge Gap Discovered
- Information you didn't know
- Outdated documentation
- API behaves differently than expected
→ Log to `.learnings/LEARNINGS.md` with category `knowledge_gap`

### 5. Better Approach Found
- Discovered more efficient solution
- Found best practice
- Identified recurring pattern
→ Log to `.learnings/LEARNINGS.md` with category `best_practice`

## Logging Format

### Learning Entry (LEARNINGS.md)

```markdown
## [LRN-YYYYMMDD-XXX] category

**Logged**: 2025-01-15T10:00:00Z
**Priority**: low | medium | high | critical
**Status**: pending
**Area**: frontend | backend | infra | tests | docs | config

### Summary
One-line description

### Details
Full context and explanation

### Suggested Action
Specific fix or improvement

### Metadata
- Source: conversation | error | user_feedback
- Related Files: path/to/file.ext
- Tags: tag1, tag2

---
```

### Error Entry (ERRORS.md)

```markdown
## [ERR-YYYYMMDD-XXX] command_name

**Logged**: 2025-01-15T10:00:00Z
**Priority**: high
**Status**: pending

### Summary
What failed

### Error
```
Error message here
```

### Context
- Command attempted
- Environment details

### Suggested Fix
Possible solution

### Metadata
- Reproducible: yes | no

---
```

### Feature Request (FEATURE_REQUESTS.md)

```markdown
## [FEAT-YYYYMMDD-XXX] feature_name

**Logged**: 2025-01-15T10:00:00Z
**Priority**: medium
**Status**: pending

### Requested Capability
What user wants to do

### User Context
Why they need it

### Suggested Implementation
How to build it

### Metadata
- Frequency: first_time | recurring

---
```

## ID Format

`TYPE-YYYYMMDD-XXX`
- TYPE: `LRN` (learning), `ERR` (error), `FEAT` (feature)
- YYYYMMDD: Current date
- XXX: Sequential number (001, 002, etc.)

Examples: `LRN-20250115-001`, `ERR-20250115-002`

## Priority Guidelines

| Priority | When |
|----------|------|
| critical | Blocks core functionality, security issue |
| high | Significant impact, recurring issue |
| medium | Moderate impact, workaround exists |
| low | Minor inconvenience, edge case |

## Best Practices

1. **Log immediately** - Fresh context is valuable
2. **Be specific** - Help future understanding
3. **Include examples** - Show actual errors/solutions
4. **Link related files** - Make fixes actionable
5. **Promote learnings** - Add to CLAUDE.md when broadly applicable
6. **Review regularly** - Keep learnings current

## Promote to Project Memory

When a learning applies broadly, add to:

- **CLAUDE.md** - Project conventions and gotchas
- **AGENTS.md** - Agent workflows and patterns  
- **.github/copilot-instructions.md** - Copilot context

### Example Promotion

**Learning** (verbose):
> Project uses pnpm workspaces. npm install failed. Must use pnpm install.

**In CLAUDE.md** (concise):
```markdown
## Build & Dependencies
- Package manager: pnpm (not npm)
- Use `pnpm install` for dependencies
```

## Review Checklist

Before starting major tasks:
- [ ] Check `.learnings/` for related issues
- [ ] Review pending high-priority items
- [ ] Link new learnings to existing ones

After completing tasks:
- [ ] Evaluate if knowledge emerged
- [ ] Log unexpected discoveries
- [ ] Consider skill extraction for valuable patterns
