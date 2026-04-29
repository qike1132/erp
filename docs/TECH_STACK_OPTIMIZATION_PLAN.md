# ERP系统技术栈优化方案

## 一、当前技术栈分析

### 后端（Python）
- **框架**: FastAPI 0.136.0 + Uvicorn
- **数据库**: SQLAlchemy 2.0.49 + PostgreSQL (asyncpg/psycopg)
- **异步任务**: Celery 5.6.3 + Redis
- **数据验证**: Pydantic 2.13.2
- **数据处理**: Pandas 2.2.3 + OpenPyXL 3.1.5
- **OCR**: RapidOCR 3.8.0 + RapidOCRPDF + RapidTable + ONNX Runtime + OpenCV
- **监控**: Prometheus + Sentry + Structlog
- **开发工具**: Ruff + MyPy + Bandit

### 前端（Vue3）
- **框架**: Vue 3.5.33 + Vite 8.0.0 + TypeScript 5.9.3
- **状态管理**: Pinia 3.0.4
- **路由**: Vue Router 4.6.4
- **UI组件**: Reka UI 2.9.6 (基于Radix UI的无头组件库)
- **样式**: TailwindCSS 4.2.4
- **图表**: ECharts 6.0.0
- **数据获取**: TanStack Query 5.100.5

### Android
- **框架**: Kotlin + Jetpack Compose
- **依赖注入**: Hilt
- **网络**: Retrofit + OkHttp
- **本地存储**: Room + DataStore

## 二、优化方案

### ✅ 已实施优化

#### 1. 依赖版本约束优化
**问题**: 依赖版本固定过严（==），无法获得安全补丁和bug修复
**解决方案**: 将所有依赖从`==`改为`~=`
- `fastapi==0.136.0` → `fastapi~=0.136.0` (允许0.136.x版本)
- 优点: 自动获得小版本的安全补丁和bug修复
- 风险: 需要定期测试兼容性
- **状态**: 已完成

### 📋 建议优化

#### 2. OCR功能优化（保持现状）
**分析**: 
- OCR是核心业务功能（出货单识别）
- 使用RapidOCR + RapidOCRPDF + RapidTable + OpenCV + numpy
- 有复杂的表格解析和模糊匹配逻辑
- 离线OCR，数据隐私安全

**建议**: **保持现状**
- 理由: OCR是核心功能，云API会增加成本和隐私风险
- 可选优化: 
  - 添加OCR模型懒加载（已实现延迟初始化）
  - 考虑添加OCR结果缓存（Redis）
  - 监控OCR性能指标（识别时间、准确率）

#### 3. Celery简化评估
**分析**:
- Celery配置完善（队列路由、重试机制、监控）
- 任务主要是批量导入订单/备货
- 任务逻辑简单但有可靠性要求

**建议**: **保持Celery**
- 理由: 
  - 批量导入任务需要可靠性和重试机制
  - Celery提供了完善的任务队列和监控（Flower）
  - 当前配置已经优化（并发、内存限制、连接池）
- 可选优化: 
  - 如果任务量极小（<10次/天），可考虑FastAPI BackgroundTasks
  - 但建议保持Celery以支持未来扩展

#### 4. 前端组件库迁移建议
**当前**: Reka UI 2.9.6 (基于Radix UI的无头组件库)
**分析**:
- Reka UI生态相对小众
- 社区支持较弱，文档和教程较少
- 基于Radix UI，质量有保障

**建议**: **保持Reka UI或迁移到Element Plus**
- **保持Reka UI**: 如果团队熟悉Radix UI生态
  - 优点: 无头组件，样式完全可控
  - 缺点: 社区小，学习成本高
- **迁移到Element Plus**: 
  - 优点: 
    - 国内生态完善，文档丰富
    - 社区活跃，问题易解决
    - 组件齐全，开箱即用
  - 缺点: 
    - 需要迁移现有组件（7个UI组件）
    - 样式定制可能受限
  - 迁移成本: 中等（约2-3天）
- **迁移到Naive UI**:
  - 优点: TypeScript友好，主题系统强大
  - 缺点: 学习成本中等

**推荐**: 如果团队规模小、需要快速迭代，建议迁移到Element Plus；如果追求样式定制性，保持Reka UI

#### 5. 跨平台架构优化
**当前**: Web (Vue3) + Android (Kotlin) + 桌面管理器 (Python/pystray)
**分析**: 三端维护成本高

**建议**: 
- **短期**: 保持现状，专注核心业务
- **长期考虑**: 如果需要iOS支持，评估Flutter
  - Flutter可统一Android/iOS/Web
  - 但需要重写现有Android代码
  - 迁移成本高（约1-2个月）

#### 6. 数据库优化
**当前**: PostgreSQL + SQLAlchemy 2.0
**建议**: **保持现状**
- SQLAlchemy 2.0是最新版本，异步支持完善
- PostgreSQL适合ERP系统的复杂查询
- 可选优化:
  - 添加数据库连接池监控
  - 定期分析慢查询（pg_stat_statements）

#### 7. 缓存策略优化
**当前**: Redis + hiredis
**建议**: 
- 添加缓存策略文档
- 对高频查询（产品列表、客户列表）添加缓存
- 设置合理的TTL（如5-15分钟）

#### 8. 监控和日志优化
**当前**: Prometheus + Sentry + Structlog
**建议**:
- 添加业务指标监控（订单量、库存预警）
- 统一日志格式（JSON结构化日志）
- 添加APM工具（如Sentry Performance）

## 三、优先级排序

### 高优先级（立即执行）
1. ✅ 依赖版本约束优化（已完成）
2. 添加OCR结果缓存（减少重复计算）
3. 添加高频查询缓存（产品、客户列表）

### 中优先级（1-2周内）
4. 评估前端组件库迁移（Reka UI → Element Plus）
5. 添加业务指标监控
6. 优化日志格式和聚合

### 低优先级（长期规划）
7. 跨平台架构评估（Flutter）
8. 数据库慢查询优化
9. 添加APM工具

## 四、实施建议

### 立即可执行的优化
```bash
# 1. 更新依赖（已优化版本约束）
pip install --upgrade -r requirements/base.txt

# 2. 添加OCR缓存（伪代码）
# 在ocr_service.py中添加Redis缓存
@lru_cache(maxsize=100)
def extract_text_cached(file_hash: str, file_content: bytes):
    # 检查Redis缓存
    # 缓存未命中则执行OCR
    # 存储结果到Redis
    pass
```

### 前端组件库迁移步骤（如果决定迁移）
1. 安装Element Plus: `npm install element-plus @element-plus/icons-vue`
2. 在main.ts中引入: `import ElementPlus from 'element-plus'`
3. 逐个迁移组件（Checkbox、Select、Dialog、DatePicker、Tabs）
4. 测试所有使用这些组件的页面
5. 移除reka-ui依赖

## 五、总结

### 当前技术栈评分
- **后端**: 8.5/10（FastAPI选择优秀，依赖合理）
- **前端**: 7.5/10（Vue3+Vite优秀，但组件库生态较弱）
- **Android**: 8.5/10（Jetpack Compose是最新趋势）
- **整体架构**: 8/10（三端分离但维护成本高）

### 核心建议
1. **保持OCR和Celery** - 它们是核心功能，配置合理
2. **优化依赖管理** - 已完成，允许小版本更新
3. **评估前端组件库** - 根据团队情况选择迁移或保持
4. **添加缓存层** - 减少重复计算，提升性能
5. **完善监控** - 添加业务指标，便于问题定位

### 风险提示
- 依赖版本放宽后需要定期测试兼容性
- 前端组件库迁移需要2-3天，需安排在业务低峰期
- 跨平台重构成本高，建议仅在必要时进行

---

**文档版本**: v1.0  
**创建日期**: 2026-04-27  
**评估人**: Cascade AI Assistant
