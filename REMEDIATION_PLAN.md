# 代码质量整改执行方案 (基于 1.md 评估报告)

> 核实日期: 2026-04-12 | 项目: ERP系统(滨发协同系统)

---

## 一、问题核实结果

| 编号 | 文档描述 | 核实结论 | 实际严重度 |
|------|---------|---------|-----------|
| CRIT-001 | 硬编码SECRET_KEY | **确认** - FastAPI默认值"CHANGE-ME-IN-PRODUCTION"，Flask侧生产模式已有强制检查 | Critical |
| CRIT-002 | SQL注入-__import__ | **标签不准** - 非SQL注入，ORM参数化查询；但__import__是代码坏味道 | Medium |
| CRIT-003 | 异常信息泄露 | **部分确认** - logger.exception仅服务端日志，客户端返回通用消息 | Low |
| CRIT-004 | CORS过于宽松 | **未确认** - 默认仅允许3个localhost域名 | Low |
| CRIT-005 | 会话固定攻击 | **部分确认** - 缺少会话过期/轮换，但签名验证存在 | Medium |
| HIGH-001 | N+1查询 | **确认** - 重新查询时缺少selectinload | High |
| HIGH-002 | 缺少索引 | **部分确认** - 仅MaterialRegistrationItem.material_name缺失 | Medium |
| HIGH-003 | 敏感信息日志 | **未确认为敏感** - print()非敏感数据，但应替换为logger | Low |
| HIGH-004 | 缺少速率限制 | **确认** - FastAPI完全无速率限制 | High |
| HIGH-005 | 文件上传路径 | **部分确认** - UUID防遍历，但缺文件大小限制 | Medium |
| HIGH-006 | JWT过期时间过长 | **确认** - 480分钟(8小时) | High |
| HIGH-007 | 缺少输入长度限制 | **确认** - Query参数无max_length | Medium |
| HIGH-008 | 密码复杂度不完整 | **确认** - 缺少常见弱密码检查 | Medium |
| HIGH-009 | Redis无认证 | **确认** - 默认空密码(.env已有密码) | Medium |
| HIGH-010 | 缺少CSRF保护 | **确认** - FastAPI无CSRF中间件 | High |
| HIGH-011 | Excel模板路径 | **确认** - 未验证路径范围 | Low |
| HIGH-012 | 连接池配置不合理 | **确认** - 硬编码，同步5/异步10不一致 | High |
| HIGH-013 | 缺少查询超时 | **确认** - 无pool_timeout和查询超时 | Medium |
| HIGH-014 | 缺少请求体大小限制 | **确认** - 无body size限制 | High |
| HIGH-015 | 缺少API版本废弃 | **确认** - 无deprecation响应头 | Low |
| HIGH-016 | 错误响应不统一 | **确认** - 各端点错误格式不一致 | Medium |
| HIGH-017 | 健康检查不完整 | **确认** - 仅返回静态值 | Medium |
| HIGH-018 | 缓存键无命名空间 | **确认** - key_prefix仅'erp:' | Low |
| MED-001 | 导入顺序不规范 | **确认** - auxiliary.py三重复代码块严重违规 | High |
| MED-002 | 函数复杂度过高 | **确认** - _generate_factory_summary_print圈复杂度>15 | Medium |
| MED-003 | 重复代码块 | **确认** - 3个HTML生成函数共享结构 | Medium |
| MED-005 | 魔法数字 | **确认** - database.py连接池参数硬编码 | Medium |

---

## 二、分阶段执行计划

### Phase 1: CRITICAL级别修复

| 任务 | 修复措施 | 验收标准 |
|------|---------|---------|
| CRIT-001 | FastAPI config.py移除SECRET_KEY默认值，启动时校验 | 无SECRET_KEY时拒绝启动 |
| CRIT-002 | 替换所有__import__为正常import语句 | 无__import__动态导入 |
| CRIT-005 | deps.py添加session max_age验证 | 过期会话被正确拒绝 |

### Phase 2: HIGH级别安全加固

| 任务 | 修复措施 | 验收标准 |
|------|---------|---------|
| HIGH-004 | 安装slowapi，配置登录5次/分钟，全局60次/分钟 | 超限请求返回429 |
| HIGH-006 | ACCESS_TOKEN_EXPIRE_MINUTES改为60 | 访问令牌60分钟过期 |
| HIGH-009 | 移除Redis空密码默认值，缺少密码时告警 | 配置不安全时日志警告 |
| HIGH-010 | 添加CSRF保护中间件(SameSite+双重提交) | POST请求需CSRF验证 |
| HIGH-014 | 添加请求体大小限制中间件10MB | 超大请求被拒绝 |
| HIGH-007 | Query参数添加max_length=100 | 超长输入验证失败 |
| HIGH-005 | 文件上传添加5MB大小限制 | 超大文件被拒绝 |
| HIGH-008 | 添加常见弱密码黑名单 | 常见弱密码被拒绝 |

### Phase 3: HIGH级别基础设施

| 任务 | 修复措施 | 验收标准 |
|------|---------|---------|
| HIGH-012 | 从环境变量读取连接池参数(.env已有DB_POOL_SIZE等) | .env参数生效 |
| HIGH-001 | 重新查询时添加selectinload | 无N+1查询 |
| HIGH-013 | 添加pool_pre_ping=True | 连接断开自动重连 |
| HIGH-017 | 添加DB/Redis连通性检查 | 依赖不可用返回503 |
| HIGH-016 | 添加全局异常处理器统一错误格式 | 所有错误统一JSON格式 |
| HIGH-002 | MaterialRegistrationItem.material_name添加索引 | EXPLAIN验证 |

### Phase 4: MEDIUM级别代码质量

| 任务 | 修复措施 | 验收标准 |
|------|---------|---------|
| MED-001 | auxiliary.py删除三重复代码块，保留一份 | 无重复路由 |
| MED-002/003 | 提取公共HTML模板函数 | 共享base template |
| CRIT-003/HIGH-003 | app/__init__.py中print替换为logger | 无print语句 |

### Phase 5: LOW级别及收尾

| 任务 | 修复措施 |
|------|---------|
| HIGH-018 | 缓存键添加实例ID命名空间 |
| HIGH-015 | 添加X-API-Version响应头 |

---

## 三、风险控制

- 每Phase完成后运行语法检查和启动验证
- 安全相关修改(.env, config.py)保持向后兼容
- 不引入文档要求范围外的新功能
