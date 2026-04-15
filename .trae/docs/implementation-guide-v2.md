# Trae AI Agent系统 v2.0 实施指南

## 🚀 快速开始

### 1. 系统要求
- Node.js >= 18.0
- 内存 >= 4GB
- 磁盘空间 >= 1GB

### 2. 安装步骤

```bash
# 1. 备份现有配置
cp -r .trae .trae-backup-v1

# 2. 创建核心目录结构（如果不存在）
mkdir -p .trae/core/{query-engine,transport,skills}
mkdir -p .trae/config
mkdir -p .trae/docs

# 3. 验证配置文件完整性
ls -la .trae/core/query-engine/
ls -la .trae/core/transport/
ls -la .trae/core/skills/
ls -la .trae/config/
```

### 3. 配置验证

```bash
# 验证JSON配置文件格式
for file in .trae/core/**/*.json .trae/config/*.json; do
  echo "Validating: $file"
  python -c "import json; json.load(open('$file'))" && echo "✅ Valid" || echo "❌ Invalid"
done
```

---

## 📖 核心模块使用指南

### 一、QueryGuard 安全防护使用示例

#### 场景1：输入验证与过滤

```javascript
const queryGuard = new QueryGuard('.trae/core/query-engine/query-guard.json');

async function safeExecute(agentName, action, input) {
  // Step 1: 权限检查
  if (!queryGuard.validatePermission(agentName, action)) {
    throw new Error(`Permission denied: ${agentName} cannot perform ${action}`);
  }
  
  // Step 2: 速率限制检查
  if (!queryGuard.checkRateLimit(agentName)) {
    throw new Error('Rate limit exceeded');
  }
  
  // Step 3: 输入过滤
  const sanitizedInput = queryGuard.sanitizeInput(input);
  
  // Step 4: 恶意请求检测
  if (queryGuard.detectMaliciousRequest(sanitizedInput)) {
    await quarantineRequest(agentName, sanitizedInput);
    throw new Error('Malicious request detected');
  }
  
  // Step 5: 记录安全审计日志
  queryGuard.logSecurityEvent({
    type: 'request_validated',
    agent: agentName,
    action: action,
    timestamp: new Date(),
    status: 'approved'
  });
  
  // 执行经过安全检查的请求
  return await executeAction(action, sanitizedInput);
}
```

#### 场景2：自定义安全规则

```javascript
// 添加自定义安全规则
queryGuard.addCustomRule({
  name: 'sql_injection_prevention',
  pattern: /(?:SELECT|INSERT|UPDATE|DELETE|DROP)\s+.*FROM\s+/i,
  handler: (input) => {
    blockRequest('Potential SQL injection detected');
    logSecurityEvent({
      type: 'security_violation',
      severity: 'critical',
      rule: 'sql_injection_prevention',
      input: input
    });
  },
  priority: 100,
  enabled: true
});
```

---

### 三、CircuitBreaker 熔断器使用示例

#### 场景1：保护关键API调用

```javascript
const circuitBreaker = new CircuitBreaker(
  '.trae/core/transport/circuit-breaker.json',
  'api-gateway'
);

async function callAPIWithCircuitBreaker(endpoint, data) {
  try {
    const response = await circuitBreaker.execute(async () => {
      return await fetch(endpoint, {
        method: 'POST',
        body: JSON.stringify(data),
        headers: { 'Content-Type': 'application/json' }
      });
    });
    
    circuitBreaker.recordSuccess();
    return response;
    
  } catch (error) {
    circuitBreaker.recordFailure();
    
    if (circuitBreaker.getState() === CircuitState.OPEN) {
      // 熔断开启，使用降级方案
      console.error('⚠️ Circuit breaker OPEN for', endpoint);
      return getFallbackResponse(endpoint);
    }
    
    throw error;
  }
}

// 监控熔断状态变化
circuitBreaker.onStateChange((oldState, newState) => {
  logAlert(`Circuit breaker state changed: ${oldState} → ${newState}`);
  
  if (newState === CircuitState.OPEN) {
    notifyTeam('API Gateway circuit breaker opened');
  } else if (newState === CircuitState.CLOSED) {
    notifyTeam('API Gateway recovered');
  }
});
```

#### 场景2：多层级熔断策略

```javascript
// 为不同优先级的操作设置不同的熔断阈值
const criticalBreaker = new CircuitBreaker(config, {
  failureThreshold: 3,
  timeout: 15000,
  name: 'critical-operations'
});

const normalBreaker = new CircuitBreaker(config, {
  failureThreshold: 5,
  timeout: 30000,
  name: 'normal-operations'
});

async function executeWithPriority(priority, operation) {
  const breaker = priority === 'critical' ? criticalBreaker : normalBreaker;
  return await breaker.execute(operation);
}
```

---

### 四、RetryPolicy 智能重试使用示例

#### 场景1：带退避的重试机制

```javascript
const retryPolicy = new RetryPolicy('.trae/core/transport/retry-policy.json');

async function fetchWithRetry(url, options = {}) {
  return await retryPolicy.executeWithRetry(
    async () => {
      const response = await fetch(url, options);
      
      if (!response.ok) {
        throw new Error(`${response.status} ${response.statusText}`);
      }
      
      return response.json();
    },
    {
      maxRetries: 3,
      initialDelay: 1000,
      backoffMultiplier: 2.0,
      retryableErrors: ['ECONNRESET', 'ETIMEDOUT', '503', '504']
    }
  );
}
```

#### 场景2：自适应重试策略

```javascript
// 根据历史失败率自动调整重试参数
const adaptiveRetry = new AdaptiveRetryPolicy(retryPolicy);

adaptiveRetry.enableLearning(true);

async function smartRetry(operation) {
  return await adaptiveRetry.execute(operation, {
    adaptBasedOnHistory: true,
    maxRetries: 5,
    learnFromFailures: true
  });
}
```

---

### 五、Skill 技能热重载使用示例

#### 场景1：监听技能变更

```javascript
const skillWatcher = new SkillWatcher('.trae/core/skills/hot-reloader.json');

// 启动文件监听
skillWatcher.watch();

// 注册事件处理器
skillWatcher.on('change', async (event) => {
  console.log(`📝 Skill changed: ${event.path}`);
  
  if (event.type === 'add') {
    // 新技能被发现
    const skillInfo = skillWatcher.loadSkill(event.path);
    console.log(`✅ New skill loaded: ${skillInfo.name}`);
    
  } else if (event.type === 'change') {
    // 技能被修改，执行热重载
    await hotReloader.safeReload(event.skillName);
    console.log(`🔄 Skill reloaded: ${event.skillName}`);
    
  } else if (event.type === 'unlink') {
    // 技能被删除
    skillWatcher.unloadSkill(event.skillName);
    console.log(`❌ Skill unloaded: ${event.skillName}`);
  }
});

skillWatcher.on('error', (error) => {
  console.error('Skill watcher error:', error);
  notifyAdmin('Skill watcher encountered an error');
});
```

#### 场景2：批量技能管理

```javascript
// 批量重新加载所有修改过的技能
async function reloadModifiedSkills() {
  const modifiedSkills = skillWatcher.getModifiedSkills();
  
  if (modifiedSkills.length > 0) {
    console.log(`🔄 Reloading ${modifiedSkills.length} modified skills...`);
    
    const result = await hotReloader.batchReload(modifiedSkills);
    
    console.log(`✅ Reloaded ${result.successful.length} skills successfully`);
    
    if (result.failed.length > 0) {
      console.warn(`⚠️ Failed to reload ${result.failed.length} skills:`);
      result.failed.forEach(failure => {
        console.warn(`  - ${failure.skill}: ${failure.error}`);
      });
    }
  }
}

// 定期检查并重载
setInterval(reloadModifiedSkills, 60000); // 每分钟检查一次
```

---

## 🧪 测试指南

### 端到端测试

```bash
# 运行配置文件验证测试
python -m pytest .trae/tests/test_config_e2e.py -v

# 预期结果: 37个测试全部通过
```

### 压力测试

```bash
# 运行熔断器和重试机制压力测试
python -m pytest .trae/tests/test_stress.py -v -s

# 性能基准:
# - 熔断器性能: > 100万 ops/s
# - 重试策略性能: > 80万 ops/s
```

### 安全审计

```bash
# 运行安全审计
python .trae/tests/security_audit.py

# 预期结果: 未发现安全问题
```

---

## 🔧 高级配置

### 自定义熔断阈值

编辑 `.trae/core/transport/circuit-breaker.json`：

```json
{
  "perTransport": {
    "websocket": {
      "failureThreshold": 3,
      "timeout": 15000,
      "monitoringWindow": 30000,
      "halfOpenMaxCalls": 2,
      "recoveryStrategy": "gradual"
    }
  }
}
```

### 自定义技能发现规则

编辑 `.trae/core/skills/hot-reloader.json`：

```json
{
  "skillDiscovery": {
    "autoDiscover": true,
    "discoveryDepth": 5,
    "customPatterns": [
      { "pattern": "**/*-agent*/**", "type": "agent" },
      { "pattern": "**/*-tool*/**", "type": "tool" },
      { "pattern": "**/*-skill*/**", "type": "skill" }
    ]
  }
}
```

---

## 📊 监控与调试

### 性能监控仪表盘访问

```bash
# 启动监控服务（如果已实现）
npm run start-monitoring

# 或查看实时日志
tail -f .trae/logs/performance.log
```

### 常用监控命令

```bash
# 查看当前Token使用情况
node scripts/check-token-usage.js

# 查看熔断状态
node scripts/check-circuit-status.js

# 查看已加载技能列表
node scripts/list-loaded-skills.js

# 查看性能报告
node scripts/generate-performance-report.js --range 24h
```

### 调试模式启用

在 `agent-system-v2.json` 中设置：

```json
{
  "debug": {
    "enabled": true,
    "logLevel": "verbose",
    "logToFile": true,
    "includeStackTraces": true,
    "slowQueryThreshold": 1000
  }
}
```

---

## ⚠️ 故障排除

### 问题1：熔断器频繁触发

**症状**: CircuitBreaker经常进入OPEN状态

**解决方案**:
1. 降低failureThreshold值
2. 增加timeout时间
3. 检查网络连接稳定性
4. 优化下游服务的性能

### 问题3：技能热重载失败

**症状**: 技能修改后没有生效或报错

**解决方案**:
1. 检查技能文件的JSON格式
2. 确认SKILL.md文件存在且格式正确
3. 查看hot-reloader日志获取详细错误信息
4. 手动测试技能加载：`node scripts/test-skill-load.js <skill-name>`

---

## 🎯 最佳实践

### 1. 安全防护最佳实践

- ✅ 启用所有QueryGuard功能
- ✅ 定期审查安全日志
- ✅ 及时更新阻止模式列表
- ✅ 对敏感操作要求显式权限
- ❌ 不要在生产环境禁用输入验证
- ❌ 不要忽略安全告警

### 3. 容错处理最佳实践

- ✅ 为所有外部调用添加熔断保护
- ✅ 设置合理的重试次数和延迟
- ✅ 实现优雅的降级方案
- ✅ 监控熔断状态变化
- ❌ 不要无限重试
- ❌ 不要忽略熔断告警

### 4. 技能管理最佳实践

- ✅ 保持技能文件结构清晰
- ✅ 使用版本控制管理技能变更
- ✅ 测试技能的热重载功能
- ✅ 定期清理未使用的技能
- ❌ 不要在运行时手动删除技能文件
- ❌ 不要忽略技能加载错误

---

## 📚 相关文档

- [架构设计文档](./agent-system-v2-upgrade-plan.md)
- [Claude CLI分析报告](../claude-cli-analysis-report.md)
- [Agent协同最高指令](../rules/agent-orchestration-supreme-directive.md)
- [项目开发规则](../rules/project-rules.md)

---

## 💡 下一步计划

1. **Week 1-2**: 基础设施搭建完成
2. **Week 3-4**: 通信层增强实现
3. **Week 5-6**: 技能系统升级
4. **Week 7-8**: 监控与分析完善
5. **Week 9-10**: 集成测试与优化

---

**文档版本**: v2.0.0
**最后更新**: 2026-04-07
**维护者**: Solo Coder 总指挥
