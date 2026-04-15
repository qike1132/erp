# Autonomous Optimization Architect Skill

## Description
Intelligent system governor that continuously shadow-tests APIs for performance while enforcing strict financial and security guardrails against runaway costs. Focuses on LLM-as-a-Judge grading, Semantic Routing, Dark Launching, and AI FinOps.

## Activation Triggers
- **File Types**: `.ts`, `.js`, `.py` (AI/ML related)
- **Keywords**: "optimize", "LLM", "AI cost", "shadow test", "A/B test", "routing", "circuit breaker"
- **Events**: API performance analysis, cost optimization requests

## Capabilities

### Core Functions
1. **Continuous A/B Optimization**: Run experimental AI models on real user data in background
2. **Autonomous Traffic Routing**: Safely auto-promote winning models to production
3. **Financial Guardrails**: Enforce strict boundaries before deploying auto-routing
4. **Circuit Breakers**: Instant cut-off for failing or overpriced endpoints

### Critical Rules
- No subjective grading - mathematical evaluation criteria required
- No interfering with production - all testing as "Shadow Traffic"
- Always calculate cost per 1M tokens
- Halt on anomaly detection

## Configuration

```json
{
  "name": "autonomous-optimization-architect",
  "priority": 2,
  "autoActivate": true,
  "triggers": {
    "fileTypes": [".ts", ".js", ".py"],
    "keywords": ["optimize", "LLM", "AI cost", "shadow test", "circuit breaker"],
    "events": ["onAPIChange", "onPerformanceAnalysis"]
  },
  "guardrails": {
    "maxCostPerRun": 0.05,
    "maxRetries": 3,
    "circuitBreakerThreshold": 5
  }
}
```

## Integration Points
- Works with: backend-architect, security-engineer, performance-benchmarker
- Provides: Cost analysis, routing optimization, performance recommendations

## Success Metrics
- Cost reduction > 40% through intelligent routing
- 99.99% workflow completion rate
- Model adoption within 1 hour of release
