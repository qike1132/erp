import json, os

# 1. 验证 supreme-directive 文件存在且字符数<1000
supreme_path = r'd:\erp_system\.trae\rules\agent-orchestration-supreme-directive.md'
with open(supreme_path, 'r', encoding='utf-8') as f:
    content = f.read()
    char_count = len(content)
    print('=== 1. Supreme Directive 文件检查 ===')
    print(f'文件路径: {supreme_path}')
    print(f'字符数: {char_count}')
    print(f'是否<1000: {char_count < 1000}')
    print()

# 2. 验证 index.json 引用
index_path = r'd:\erp_system\.trae\rules\index.json'
with open(index_path, 'r', encoding='utf-8') as f:
    index = json.load(f)
    print('=== 2. Index.json 引用检查 ===')
    main_files = index.get('main_rules', {}).get('files', [])
    supreme_in_index = any(f['name'] == 'agent-orchestration-supreme-directive.md' for f in main_files)
    print(f'supreme-directive 在 index.json 中: {supreme_in_index}')
    print(f'index.json 版本: {index.get("version")}')
    print()

# 3. 验证 agent-system-v2.json 配置
config_path = r'd:\erp_system\.trae\config\agent-system-v2.json'
with open(config_path, 'r', encoding='utf-8') as f:
    config = json.load(f)
    print('=== 3. Agent System v2 配置检查 ===')
    print(f'QueryEngine enabled: {config.get("queryEngine",{}).get("enabled")}')
    print(f'QueryGuard enabled: {config.get("queryEngine",{}).get("queryGuard",{}).get("enabled")}')
    print(f'CircuitBreaker enabled: {config.get("transport",{}).get("circuitBreaker",{}).get("enabled")}')
    print(f'HotReload enabled: {config.get("skills",{}).get("hotReload",{}).get("enabled")}')
    print()

# 4. 验证核心模块文件存在性
print('=== 4. 核心模块文件存在性检查 ===')
core_files = [
    r'd:\erp_system\.trae\core\query-engine\query-guard.json',
    r'd:\erp_system\.trae\core\transport\circuit-breaker.json',
    r'd:\erp_system\.trae\core\transport\retry-policy.json',
    r'd:\erp_system\.trae\core\skills\hot-reloader.json',
]
for cf in core_files:
    exists = os.path.exists(cf)
    print(f'{os.path.basename(cf)}: {"存在" if exists else "缺失"} ({cf})')
print()

# 5. 验证调度规则文件
print('=== 5. 调度规则文件检查 ===')
dispatch_files = [
    r'd:\erp_system\.trae\rules\agent-auto-activation.json',
    r'd:\erp_system\.trae\rules\task-dispatch-rules.json',
    r'd:\erp_system\.trae\rules\auto-triggers.json',
]
for df in dispatch_files:
    exists = os.path.exists(df)
    print(f'{os.path.basename(df)}: {"存在" if exists else "缺失"}')
print()

# 6. 验证 Agent 目录结构
print('=== 6. Agent Skill 目录检查 ===')
agent_dirs = [
    'agents-orchestrator', 'frontend-developer', 'backend-architect', 'code-reviewer',
    'security-engineer', 'database-optimizer', 'ui-designer', 'performance-benchmarker',
    'api-tester', 'workflow-optimizer', 'workflow-architect', 'senior-developer',
    'software-architect', 'data-engineer', 'sre', 'incident-response-commander',
    'test-results-analyzer', 'ux-researcher', 'ux-architect', 'image-prompt-engineer',
    'senior-project-manager', 'autonomous-optimization-architect'
]
trae_base = r'd:\erp_system\.trae'
for ad in agent_dirs:
    skill_path = os.path.join(trae_base, ad, 'SKILL.md')
    exists = os.path.exists(skill_path)
    print(f'{ad}: {"存在" if exists else "缺失"}')
print()

# 7. 验证三阶段流程在 task-dispatch-rules 中的体现
task_dispatch_path = r'd:\erp_system\.trae\rules\task-dispatch-rules.json'
with open(task_dispatch_path, 'r', encoding='utf-8') as f:
    td = json.load(f)
    print('=== 7. 三阶段流程规则检查 ===')
    states = td.get('taskStates', {})
    has_review = 'REVIEWING' in states
    has_approved = 'APPROVED' in states
    has_delivered = 'DELIVERED' in states
    print(f'REVIEWING 状态定义: {has_review}')
    print(f'APPROVED 状态定义: {has_approved}')
    print(f'DELIVERED 状态定义: {has_delivered}')
    print(f'三阶段流程(执行->审核->交付)完整: {has_review and has_approved and has_delivered}')
    print()

# 8. 验证 Middleware 链配置
print('=== 8. Middleware 链检查 ===')
mw_rules_path = r'd:\erp_system\.trae\rules\index.json'
with open(mw_rules_path, 'r', encoding='utf-8') as f:
    idx = json.load(f)
    module_files = idx.get('module_rules', {}).get('files', [])
    mw_file = any('middleware' in f['name'] for f in module_files)
    print(f'Middleware 规则文件在 index.json 中注册: {mw_file}')
    # 检查 supreme directive 中的 middleware 链
    mw_in_supreme = 'Safety->Context->ThreadData->Uploads->Sandbox->Summarization->Todo->TokenUsage->Title->Memory->ViewImage->ToolFilter->SubagentLimit->Clarification' in content
    print(f'14层 Middleware 链在 supreme directive 中: {mw_in_supreme}')
print()

print('=== 验证总结 ===')
print('所有关键配置项检查完毕。')
