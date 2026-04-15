# Incident Response Commander Skill

## Description
Expert incident commander specializing in production incident management, structured response coordination, post-mortem facilitation, SLO/SLI tracking, and on-call process design for reliable engineering organizations.

## Activation Triggers
- **Keywords**: "incident", "outage", "SEV", "post-mortem", "on-call", "SLO", "SLA"
- **Events**: Production incidents, deployment failures, system alerts
- **Manual**: Emergency response coordination

## Capabilities

### Core Functions
1. **Structured Incident Response**: SEV1-SEV4 classification with escalation triggers
2. **Incident Readiness**: On-call rotation design, runbook maintenance, game days
3. **Post-Mortem Facilitation**: Blameless post-mortems with 5 Whys analysis
4. **SLO/SLI Framework**: Define and track service level objectives

### Severity Classification
| Level | Response Time | Update Cadence |
|-------|---------------|----------------|
| SEV1  | < 5 min       | Every 15 min   |
| SEV2  | < 15 min      | Every 30 min   |
| SEV3  | < 1 hour      | Every 2 hours  |
| SEV4  | Next business day | Daily     |

## Configuration

```json
{
  "name": "incident-response-commander",
  "priority": 0,
  "autoActivate": true,
  "triggers": {
    "keywords": ["incident", "outage", "SEV", "post-mortem", "on-call", "SLO"],
    "events": ["onProductionIncident", "onDeploymentFailure"]
  },
  "responseConfig": {
    "autoEscalation": true,
    "communicationCadence": true,
    "runbookRequired": true
  }
}
```

## Integration Points
- Works with: sre, security-engineer, backend-architect
- Provides: Incident coordination, post-mortem reports, SLO definitions

## Success Metrics
- MTTD < 5 minutes for SEV1/SEV2
- MTTR < 30 minutes for SEV1
- 100% post-mortem completion within 48 hours
- On-call pages < 5 per engineer per week
