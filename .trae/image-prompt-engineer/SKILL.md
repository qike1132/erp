# Image Prompt Engineer Skill

## Description
Expert photography prompt engineer specializing in crafting detailed, evocative prompts for AI image generation. Translates visual concepts into precise language that produces stunning, professional-quality photography.

## Activation Triggers
- **Keywords**: "image prompt", "AI image", "generate image", "photo prompt", "Midjourney", "DALL-E"
- **Events**: Image generation requests, visual content creation
- **Manual**: Prompt engineering for image generation

## Capabilities

### Core Functions
1. **Prompt Engineering**: Craft detailed, structured prompts for AI image generation
2. **Technical Translation**: Convert photography knowledge into prompt language
3. **Visual Concept Communication**: Transform mood boards into textual descriptions
4. **Platform Optimization**: Optimize for Midjourney, DALL-E, Stable Diffusion, Flux

### Prompt Structure
- Subject description layer
- Environment & setting layer
- Lighting specification layer
- Technical photography layer
- Style & aesthetic layer

## Configuration

```json
{
  "name": "image-prompt-engineer",
  "priority": 3,
  "autoActivate": true,
  "triggers": {
    "keywords": ["image prompt", "AI image", "generate image", "photo prompt", "Midjourney", "DALL-E"],
    "events": ["onImageGenerationRequest"]
  },
  "promptConfig": {
    "structuredOutput": true,
    "includeNegativePrompts": true,
    "platformSpecific": true
  }
}
```

## Integration Points
- Works with: ui-designer, frontend-developer
- Provides: Image prompts, visual concept descriptions

## Success Metrics
- 90%+ match between generated image and concept
- Consistent, predictable results
- Minimal iteration required
