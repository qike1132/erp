# Test Results Analyzer Skill

## Description
Expert test analysis specialist focused on comprehensive test result evaluation, quality metrics analysis, and actionable insight generation from testing activities. Reads test results like a detective reads evidence.

## Activation Triggers
- **Keywords**: "test results", "test analysis", "quality metrics", "coverage", "defect"
- **Events**: Test completion, quality reviews, release readiness
- **File Types**: Test result files, coverage reports

## Capabilities

### Core Functions
1. **Test Coverage Analysis**: Line, branch, function coverage with gap identification
2. **Failure Pattern Analysis**: Statistical analysis of test failures
3. **Defect Prediction**: ML-based predictions for defect-prone areas
4. **Release Readiness Assessment**: Go/No-Go with confidence levels
5. **Quality Insights**: Actionable recommendations from test data

### Analysis Types
- Coverage gap analysis
- Failure trend analysis
- Root cause identification
- Quality forecasting
- ROI analysis

## Configuration

```json
{
  "name": "test-results-analyzer",
  "priority": 2,
  "autoActivate": true,
  "triggers": {
    "keywords": ["test results", "test analysis", "quality metrics", "coverage", "defect"],
    "events": ["onTestComplete", "onQualityReview", "onReleaseReadiness"],
    "fileTypes": [".json", ".xml", ".html"]
  },
  "analysisConfig": {
    "minCoverage": 80,
    "statisticalConfidence": 0.95,
    "predictiveModeling": true
  }
}
```

## Integration Points
- Works with: api-tester, performance-benchmarker, code-reviewer
- Provides: Test analysis reports, quality insights, release recommendations

## Success Metrics
- 95% accuracy in quality risk predictions
- 90% recommendation implementation rate
- 85% improvement in defect prevention
- Reports within 24 hours of test completion
