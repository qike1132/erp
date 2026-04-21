# Flask 遗留组件下线检查清单

## 检查项

### 1. 前端页面迁移
- [ ] 确认所有 Jinja2 模板页面已在 Next.js 中实现
- [ ] 确认所有 Flask Blueprint 路由已有 FastAPI 等价实现
- [ ] 确认 Flask 专属中间件已迁移到 FastAPI
- [ ] 确认 Flask 会话（session）已迁移到 JWT/Cookie

### 2. 后端服务迁移
- [ ] 确认所有 Flask API 已在 FastAPI 中实现
- [ ] 确认 Flask 数据库模型已在 SQLAlchemy 2.0 中定义
- [ ] 确认 Flask 表单验证已迁移到 Pydantic
- [ ] 确认 Flask 模板过滤器已迁移到 Jinja2 独立使用

### 3. 配置文件更新
- [ ] 更新 `run.py`，移除 Flask 进程启动逻辑
- [ ] 更新 `docker-compose.yml`，移除 Flask 端口映射
- [ ] 更新 `nginx.conf`，移除 Flask 反向代理
- [ ] 更新 `requirements.txt`，移除 Flask 依赖

### 4. 代码归档
- [ ] 将 `app/` 目录归档到 `archive/flask_legacy/`
- [ ] 保留 `app/models/` 作为参考（双模型系统）
- [ ] 删除 `app/routes/`（FastAPI 已替代）
- [ ] 删除 `app/services/`（已迁移到 `fastapi_app/services/`）

### 5. 测试验证
- [ ] 全量回归测试通过
- [ ] 性能基准测试通过
- [ ] 安全扫描通过

### 6. 文档更新
- [ ] 更新架构文档
- [ ] 更新部署文档
- [ ] 更新开发手册

## 下线流程

```
1. 完成所有检查项
2. 备份 Flask 代码
3. 停止 Flask 进程
4. 更新配置文件
5. 重启服务
6. 验证功能正常
7. 归档代码
```

## 回滚方案

如发现问题，可快速回滚：
1. 从归档恢复 Flask 代码
2. 恢复 run.py 中的 Flask 启动逻辑
3. 重启服务
