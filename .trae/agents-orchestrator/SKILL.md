# Agents Orchestrator Skill

## Description
Autonomous pipeline manager that orchestrates the entire development workflow from specification to production-ready implementation. This is the primary coordination agent for complex multi-agent tasks.

## Activation Triggers
- **Manual**: Explicitly invoked for complex multi-step workflows
- **Keywords**: "orchestrate", "pipeline", "coordinate", "workflow", "run pipeline"
- **Events**: Project initialization, complex feature development

## Capabilities

### Core Functions
1. **Pipeline Orchestration**: Manages complete development pipeline from PM → Architect → Dev ↔ QA → Integration
2. **Quality Loop Management**: Implements continuous Dev-QA loops with automatic retry logic
3. **Agent Coordination**: Coordinates multiple specialist agents with proper context handoff
4. **State Management**: Tracks project progress and maintains pipeline state

### Workflow Phases
- Phase 1: Project Analysis & Planning
- Phase 2: Technical Architecture
- Phase 3: Development-QA Continuous Loop
- Phase 4: Final Integration & Validation

## Configuration

```json
{
  "name": "agents-orchestrator",
  "priority": 0,
  "autoActivate": false,
  "maxConcurrent": 1,
  "timeout": 300000,
  "retryLimit": 3,
  "coordination": {
    "sequential": true,
    "qualityGates": true,
    "evidenceRequired": true
  }
}
```

## Integration Points

### Agents Managed
- project-manager-senior
- backend-architect
- frontend-developer
- senior-developer
- code-reviewer
- security-engineer
- database-optimizer
- ui-designer
- ux-architect
- api-tester
- performance-benchmarker
- test-results-analyzer

### Quality Gates
- Each task must pass QA before advancing
- Maximum 3 retry attempts per task
- Evidence-based validation required
- Automatic escalation on persistent failures

## Usage Examples

```
"Please spawn an agents-orchestrator to execute complete development pipeline for this feature"
"Orchestrate the workflow from specification to deployment"
"Run the full pipeline with quality gates enabled"
```

## Success Metrics
- Complete projects delivered through autonomous pipeline
- Quality gates prevent broken functionality from advancing
- Dev-QA loops efficiently resolve issues without manual intervention
- Final deliverables meet specification requirements
