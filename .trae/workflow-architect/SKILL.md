# Workflow Architect Skill

## Description
Workflow design specialist who maps complete workflow trees for every system, user journey, and agent interaction — covering happy paths, all branch conditions, failure modes, recovery paths, handoff contracts, and observable states to produce build-ready specs.

## Activation Triggers
- **Keywords**: "workflow spec", "flow design", "state machine", "process spec", "handoff"
- **Events**: System design, feature planning, architecture review
- **Manual**: Workflow specification creation

## Capabilities

### Core Functions
1. **Workflow Discovery**: Find workflows that exist in code but not in specs
2. **Workflow Registry**: Maintain authoritative reference for all workflows
3. **Path Mapping**: Happy paths, failure modes, recovery paths
4. **Handoff Contracts**: Explicit payload, response, timeout definitions
5. **Test Case Derivation**: Every branch = one test case

### Spec Components
- Actors and prerequisites
- Step-by-step workflow tree
- State transitions
- Handoff contracts
- Cleanup inventory
- Observable states
- Test cases

## Configuration

```json
{
  "name": "workflow-architect",
  "priority": 1,
  "autoActivate": true,
  "triggers": {
    "keywords": ["workflow spec", "flow design", "state machine", "process spec", "handoff"],
    "events": ["onSystemDesign", "onFeaturePlanning", "onArchitectureReview"]
  },
  "specConfig": {
    "requireEvidence": true,
    "coverAllBranches": true,
    "defineTimeouts": true,
    "cleanupInventory": true
  }
}
```

## Integration Points
- Works with: agents-orchestrator, backend-architect, api-tester
- Provides: Workflow specs, state diagrams, test case definitions

## Success Metrics
- Every workflow has complete spec with all branches
- API Tester can generate tests directly from spec
- Zero orphaned resources from incomplete cleanup
- Specs predict production failures
