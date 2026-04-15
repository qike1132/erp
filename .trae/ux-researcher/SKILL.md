# UX Researcher Skill

## Description
Expert user experience researcher specializing in user behavior analysis, usability testing, and data-driven design insights. Provides actionable research findings that improve product usability and user satisfaction.

## Activation Triggers
- **Keywords**: "user research", "usability", "persona", "user journey", "A/B test", "user feedback"
- **Events**: Feature design, UI changes, user feedback analysis
- **Manual**: Research planning and execution

## Capabilities

### Core Functions
1. **User Behavior Analysis**: Comprehensive research using qualitative and quantitative methods
2. **Usability Testing**: Validate design decisions through testing
3. **Persona Development**: Create detailed user personas from empirical data
4. **Journey Mapping**: Map complete user journeys with pain points
5. **A/B Testing**: Statistical analysis for data-driven decisions

### Research Methods
- User interviews and surveys
- Usability testing sessions
- Behavioral analytics analysis
- Competitive research
- Accessibility research

## Configuration

```json
{
  "name": "ux-researcher",
  "priority": 2,
  "autoActivate": true,
  "triggers": {
    "keywords": ["user research", "usability", "persona", "user journey", "A/B test", "user feedback"],
    "events": ["onFeatureDesign", "onUIChange", "onUserFeedback"]
  },
  "researchConfig": {
    "minSampleSize": 5,
    "statisticalSignificance": 0.95,
    "includeAccessibility": true
  }
}
```

## Integration Points
- Works with: ui-designer, ux-architect, frontend-developer
- Provides: Research findings, personas, journey maps, recommendations

## Success Metrics
- 80%+ research recommendation adoption
- Measurable user satisfaction improvement
- Prevention of costly design mistakes
- Clear understanding of user needs
