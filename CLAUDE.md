# ERP System - Claude Code Configuration

## Project Overview
滨发协同系统 (Binfa ERP) - 全栈 ERP 系统
- **Backend**: FastAPI + PostgreSQL + Redis + Celery
- **Frontend**: Vue 3 + Vite + Element Plus
- **Android**: Kotlin + Jetpack Compose + Hilt + Firebase
- **API**: RESTful + WebSocket 实时通知

## Coding Standards
- Python: PEP 8, type hints, async/await
- Kotlin: Kotlin style guide, coroutines
- Vue: Composition API, `<script setup>`

## Key Commands
```bash
# Backend
cd fastapi_app && python -m uvicorn main:app --reload

# Frontend
cd frontend-vite && npm run dev

# Android
cd android-app && ./gradlew assembleDebug

# Database migrations
cd migrations && alembic upgrade head
```

## Skill Routing

Use gstack skills for specialized tasks:

### Planning & Review
- `/office-hours` - Product brainstorming
- `/plan-ceo-review` - Strategic review
- `/plan-eng-review` - Architecture review
- `/plan-design-review` - Design review
- `/review` - Code review on PRs

### Development
- `/autoplan` - Auto-plan features
- `/ship` - Create and merge PRs
- `/land-and-deploy` - Deploy workflow

### Quality
- `/qa` - Browser QA testing
- `/cso` - Security audit (OWASP + STRIDE)
- `/investigate` - Root cause debugging
- `/retro` - Engineering retrospective

### Design
- `/design-consultation` - Design feedback
- `/design-html` - HTML prototyping
- `/design-review` - Design review

### Operations
- `/browse` - Headless browser testing
- `/benchmark` - Performance benchmarks
- `/careful` - Extra caution mode
- `/freeze` / `/unfreeze` - Lock/unlock changes

## Available Skills
- `/office-hours` - Product ideation with 6 forcing questions
- `/plan-ceo-review` - CEO-perspective strategic challenge
- `/plan-eng-review` - Engineering architecture review
- `/plan-design-review` - Design system review
- `/design-consultation` - Design feedback session
- `/design-html` - HTML/CSS prototyping
- `/review` - Comprehensive code review
- `/ship` - PR creation and merge
- `/land-and-deploy` - Deployment workflow
- `/qa` - Browser-based QA testing
- `/cso` - Security officer audit
- `/investigate` - Debug root causes
- `/retro` - Weekly retrospective
- `/browse` - Headless browser operations
- `/benchmark` - Performance testing
- `/careful` - Extra caution mode
- `/freeze` - Lock changes
- `/unfreeze` - Unlock changes
- `/autoplan` - Auto-planning
- `/plan-devex-review` - Developer experience review
- `/devex-review` - DX audit
- `/document-release` - Release documentation
- `/codex` - Codex integration
- `/gstack-upgrade` - Update gstack
- `/learn` - Learn from project

## Notes
- Use `/browse` for all web browsing, never use MCP tools
- Run `/review` before creating PRs
- Run `/qa` on staging URLs before releases
- Run `/cso` for security audits on API changes
