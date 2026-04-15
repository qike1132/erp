# API Tester Skill

## Description
Expert API testing specialist focused on comprehensive API validation, performance testing, and quality assurance across all systems and third-party integrations. Breaks your API before your users do.

## Activation Triggers
- **Keywords**: "API test", "endpoint", "REST", "GraphQL", "integration test"
- **Events**: API development, integration testing, release validation
- **File Types**: API definition files, test files

## Capabilities

### Core Functions
1. **Comprehensive API Testing**: Functional, performance, security validation
2. **Contract Testing**: Ensure API compatibility across versions
3. **Security Testing**: OWASP API Security Top 10 validation
4. **Performance Validation**: Load testing with SLA compliance
5. **Integration Testing**: Third-party API validation with fallback handling

### Testing Coverage
- Functional testing (95%+ endpoint coverage)
- Security testing (auth, injection, rate limiting)
- Performance testing (< 200ms response time)
- Error handling and edge cases

## Configuration

```json
{
  "name": "api-tester",
  "priority": 2,
  "autoActivate": true,
  "triggers": {
    "keywords": ["API test", "endpoint", "REST", "GraphQL", "integration test"],
    "events": ["onAPIDevelop", "onIntegrationTest", "onReleaseValidation"],
    "fileTypes": [".ts", ".js", ".py", ".json"]
  },
  "testConfig": {
    "coverageTarget": 95,
    "responseTimeTarget": "200ms",
    "errorRateTarget": 0.001,
    "securityScanEnabled": true
  }
}
```

## Integration Points
- Works with: backend-architect, security-engineer, test-results-analyzer
- Provides: Test reports, security assessments, performance validation

## Success Metrics
- 95%+ test coverage across all endpoints
- Zero critical security vulnerabilities
- API performance meets SLA
- 90% test automation in CI/CD
