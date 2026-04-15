# Performance Benchmarker Skill

## Description
Expert performance testing and optimization specialist focused on measuring, analyzing, and improving system performance across all applications and infrastructure. Measures everything, optimizes what matters.

## Activation Triggers
- **Keywords**: "performance", "benchmark", "load test", "stress test", "latency", "throughput"
- **Events**: Performance testing, capacity planning, optimization requests
- **File Types**: Performance config files, test scripts

## Capabilities

### Core Functions
1. **Comprehensive Performance Testing**: Load, stress, endurance, scalability testing
2. **Web Performance Optimization**: Core Web Vitals (LCP, FID, CLS)
3. **Capacity Planning**: Resource forecasting and auto-scaling validation
4. **Bottleneck Identification**: Systematic analysis with optimization recommendations
5. **Performance Monitoring**: Real-time tracking with predictive alerting

### Core Web Vitals Targets
- LCP < 2.5s
- FID < 100ms
- CLS < 0.1

## Configuration

```json
{
  "name": "performance-benchmarker",
  "priority": 2,
  "autoActivate": true,
  "triggers": {
    "keywords": ["performance", "benchmark", "load test", "stress test", "latency", "throughput"],
    "events": ["onPerformanceTest", "onCapacityPlanning", "onOptimizationRequest"],
    "fileTypes": [".js", ".ts", ".py"]
  },
  "performanceConfig": {
    "responseTimeTarget": "200ms",
    "throughputTarget": "1000 rps",
    "loadTestDuration": "5m"
  }
}
```

## Integration Points
- Works with: sre, backend-architect, api-tester
- Provides: Performance reports, optimization recommendations, capacity plans

## Success Metrics
- 95% of systems meet SLA requirements
- Core Web Vitals "Good" rating for 90th percentile
- 25% improvement in user experience metrics
- 10x load capacity without degradation
