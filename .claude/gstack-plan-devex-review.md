# /plan-devex-review — Developer Experience Plan Review (Comate Adapted)

> DX-mode review: TTHW, magical moments, friction points, persona traces.

## Three Modes

| Mode | When to use | Behavior |
|------|------------|----------|
| DX EXPANSION | "Make the DX amazing" | Dream big, no constraint on DX scope |
| DX POLISH | Default | Focus on smoothing friction in current design |
| DX TRIAGE | "Just fix the worst" | Only address critical DX blockers |

## DX First Principles

1. **Zero friction at T0** — The first 5 minutes determine if a developer stays
2. **Incremental steps** — Each step should produce a visible result
3. **Learn by doing** — Don't explain, let them experience
4. **Errors teach** — Error messages should guide, not scold
5. **Convention over configuration** — Sensible defaults, opt-in complexity
6. **Progressive power** — Easy things easy, hard things possible
7. **Immediate feedback** — Every action should have a visible response
8. **Respect for time** — Wait time is the enemy

## Seven DX Characteristics

| Characteristic | Gold standard | Quick check |
|---------------|---------------|-------------|
| Usable | Stripe API | Can a developer complete their first task in <5 min? |
| Credible | Tailwind docs | Does the documentation match reality? |
| Findable | MDN | Can developers discover features without knowing they exist? |
| Useful | Vercel CLI | Does it solve a real pain point? |
| Valuable | GitHub Actions | Does the time saved exceed the time invested? |
| Accessible | Next.js starters | Can beginners succeed as easily as experts? |
| Desirable | Linear | Does using it feel good? |

## TTHW Benchmarks

| Rating | Time to Hello World |
|--------|-------------------|
| Champion | < 2 minutes |
| Competitive | 2-5 minutes |
| Needs Work | 5-10 minutes |
| Red Flag | > 10 minutes |

## Review Process

### Step 1: Pre-review Audit
Read: plan file, README, docs, package.json, API docs, CHANGELOG, getting-started guide.

### Step 2: Developer Persona Traces
For each persona, trace their first 5 minutes:
- **New developer** — first encounter, no prior knowledge
- **Evaluating developer** — comparing with alternatives, skeptical
- **Migrating developer** — coming from a competitor, looking for parallels
- **Power user** — already knows the basics, pushing limits

### Step 3: Friction Point Identification
For each step in the developer journey, identify:
- **Blockers** — Will stop them from proceeding
- **Speed bumps** — Will slow them down but not stop them
- **Paper cuts** — Annoying but not blocking

### Step 4: Magical Moments
Design 2-3 "delight" moments:
- What would make a developer say "wow, that's clever"?
- Where can we exceed expectations?
- What's the thing they'll tell their colleagues about?

### Step 5: DX Scorecard

```
## DX Scorecard

### TTHW
- Estimated time: <X minutes>
- Steps required: <N>
- Rating: Champion/Competitive/Needs Work/Red Flag

### Persona Trace Results
| Persona | First 5 min | Friction points | Magical moments |
|---------|------------|----------------|----------------|
| New dev | Can install + run hello | 2 speed bumps | Instant deploy |
| Evaluator | Can see value proposition | 1 blocker | Live demo |
| Migrator | Can find equivalent concepts | 3 paper cuts | Migration guide |
| Power user | Can access advanced features | 1 speed bump | CLI autocomplete |

### Friction Summary
1. [BLOCKER] <description> → <fix>
2. [SPEED BUMP] <description> → <fix>
3. [PAPER CUT] <description> → <fix>

### Magical Moments
1. <moment> → <implementation>
```

## Proactive Trigger Rules

Invoke this skill when:
- User asks about developer experience
- Building APIs, CLIs, SDKs, or documentation
- User asks "is this easy to use?"
