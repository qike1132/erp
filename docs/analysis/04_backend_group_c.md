# 后端代码质量审查报告 - C组（系统域）

> 审查时间：2026-08-19
> 审查范围：系统域核心模块（仪表盘/系统管理/用户认证/客户管理/审批管理/数据备份/通知服务）共 44 个核心文件 + 40 个 backup 包文件
> 技术栈：FastAPI + SQLAlchemy 2.0 + asyncpg + Pydantic 2.13
> 审查方法：架构分析 + 安全评估 + 代码重复检测 + 圈复杂度扫描

## 审查概览

| 模块 | 文件数 | 总行数 | 风险等级 | 主要问题数 |
| --- | --- | --- | --- | --- |
| 1. 核心业务 (dashboard) | — | — | 中 | 1 |
| 2. 系统管理 (auxiliary/ocr) | — | — | 低 | 0 |
| 3. 用户管理 (user/auth) | — | — | 低 | 0 |
| 4. 客户管理 (customer) | — | — | 低 | 1 |
| 5. 审批管理 (approval) | — | — | 低 | 1 |
| 6. 数据备份 (backup) | 40+ | ~4090 重复 | 高 | 1 |
| 7. 通知服务 (notification/fcm) | — | — | 低 | 0 |
| **合计** | **44 核心 + 40 backup = 84** | **20 728** | — | **4** |

> 风险等级判定标准：高=存在 ≥3000 行重复代码或严重安全缺陷；中=单函数 >200 行或圈复杂度高；低=职责单一、安全设计良好。

---

## 一、核心业务（dashboard）

### 1.1 文件清单与规模
- `services/dashboard_service.py`：核心仪表盘服务，含 Web/移动端数据聚合。

### 1.2 代码规范
- 全部 endpoint 使用 `Depends(get_current_user_id)` 或 `require_permission` 认证 ✅
- broad-except 都有注释说明，无 bare-except，无 except+pass ✅

### 1.3 注释覆盖率
- 移动看板容错路径注释完整（`# defensive: 移动看板单个数据卡片失败时继续加载其他卡片` 等 5 处）。

### 1.4 命名合理性
- 命名规范，按数据卡片维度划分函数。

### 1.5 圈复杂度
- **中风险**：`fetch_mobile_dashboard` 函数约 280 行，圈复杂度高，包含多个数据卡片的串行加载与容错处理。**建议**：按卡片维度拆分为 `_fetch_kpi_card` / `_fetch_order_card` / `_fetch_inventory_card` 等子函数。

### 1.6 代码重复
- 无明显重复。

### 1.7 潜在缺陷
- **SQL 注入风险低**：`dashboard_service.py` 使用 f-string 拼接物化视图名（`mv_name`），但 `mv_name` 为硬编码常量（非用户输入），已标 `# nosec B608`，风险低。

### 1.8 风险等级评估
**中**。圈复杂度高，需拆分大函数。

---

## 二、系统管理（auxiliary / ocr）

### 2.1 文件清单与规模
- `services/auxiliary_service.py`：辅助业务服务
- `services/ocr_service.py`：OCR 文本抽取
- `services/ocr_import.py`：OCR 数据导入

### 2.2 代码规范
- 异常处理规范，broad-except 附注释（`# defensive: 领域事件发布失败不应影响出库主流程` 等）。

### 2.3 注释覆盖率
- 覆盖良好。

### 2.4 命名合理性
- 命名规范。

### 2.5 圈复杂度
- 适中。

### 2.6 代码重复
- 无明显重复。

### 2.7 潜在缺陷
- **路径遍历防护良好**：`ocr_service.py` 从内存 stream 打开 PDF，不直接读取文件系统路径 ✅
- **filename 仅用于日志**：`ocr_import.py` 中 filename 不参与文件路径构造，无遍历风险 ✅
- **命令注入**：未发现 `subprocess` / `eval` / `exec` 调用 ✅

### 2.8 风险等级评估
**低**。安全设计良好。

---

## 三、用户管理（user / auth）

### 3.1 文件清单与规模
- `services/user_service.py`：用户 CRUD + 权限管理
- `services/auth_service.py`：认证授权

### 3.2 代码规范
- 全部 endpoint 使用 `Depends(get_current_user_id)` 或 `require_permission` 认证 ✅

### 3.3 注释覆盖率
- 覆盖良好。

### 3.4 命名合理性
- 命名规范。

### 3.5 圈复杂度
- 适中。

### 3.6 代码重复
- 无明显重复。

### 3.7 潜在缺陷
- **密码存储安全**：Argon2id + 时序攻击防护 + 哈希迁移 ✅
- 无 bare-except、无 except+pass ✅

### 3.8 风险等级评估
**低**。安全设计良好。

---

## 四、客户管理（customer）

### 4.1 文件清单与规模
- `services/customer_service.py`：客户 CRUD
- `services/customer_sampling/`：客户抽样子包（已从 1619 行上帝服务拆分）✅

### 4.2 代码规范
- 异常处理规范。

### 4.3 注释覆盖率
- 覆盖良好。

### 4.4 命名合理性
- **低风险-命名**：`customer_service.py` 第 39 行手动转义 LIKE（`customer.replace('%', '\\%')` 等），应使用 `escape_like` 函数。**建议**：迁移至 `fastapi_app.core.sanitizer.escape_like`。

### 4.5 圈复杂度
- 适中。

### 4.6 代码重复
- 无明显重复。

### 4.7 潜在缺陷
- `customer_sampling` 已从 1619 行上帝服务拆分为子包 ✅，架构改进良好。

### 4.8 风险等级评估
**低**。已完成的拆分良好，仅剩命名小问题。

---

## 五、审批管理（approval）

### 5.1 文件清单与规模
- `services/approval_service.py`：审批流服务

### 5.2 代码规范
- 全部写操作使用 `with_for_update` 行级锁 ✅
- 模块顶部说明并发安全策略 ✅

### 5.3 注释覆盖率
- 覆盖良好。

### 5.4 命名合理性
- 命名规范。

### 5.5 圈复杂度
- 适中。

### 5.6 代码重复
- 无明显重复。

### 5.7 潜在缺陷
- **TODO（低风险）**：`approval_service.py` 2 处 `TODO(multi-sku-order)`（第 7、321 行），标识多 SKU 订单下 `order.product_id` / `order.quantity` 兼容值处理待重构。与 B 组 stock_service 的 TODO 同源，需统一排期。

### 5.8 风险等级评估
**低**。TODO 待完成，不影响当前功能。

---

## 六、数据备份（backup）— 高风险

### 6.1 文件清单与规模

| 子模块 | 文件 | 行数 | 重复副本 |
| --- | --- | --- | --- |
| orchestration/ | recovery_test_service.py | 1106 | ×2 |
| orchestration/ | policy_service.py | 613 | ×2 |
| orchestration/ | core.py | 325 | ×2 |
| verify/ | health_check_service.py | 650 | ×2 |
| verify/ | query_service.py | 86 | ×2 |
| verify/ | core.py | 219 | ×2 |
| **重复总计** | — | **~4090** | — |

### 6.2 代码规范
- broad-except 都有注释说明（`# defensive: recovery test orchestration must report failure gracefully` 等），无 bare-except，无 except+pass ✅

### 6.3 注释覆盖率
- 覆盖良好，容错路径注释完整。

### 6.4 命名合理性
- 命名规范。

### 6.5 圈复杂度
- `recovery_test_service.py` 1106 行，单文件偏大。

### 6.6 代码重复
- **高风险-代码重复**：`backup` 包存在两套几乎完全相同的目录：
  - `orchestration/` 与 `orchestration_dir/`：`recovery_test_service.py`（1106 行×2）、`policy_service.py`（613 行×2）、`core.py`（325 行×2）**完全相同**
  - `verify/` 与 `verify_dir/`：`health_check_service.py`（650 行×2）、`query_service.py`（86 行×2）、`core.py`（219 行×2）**几乎相同**
  - **总计约 4090 行重复代码**

### 6.7 潜在缺陷
- **备份加密安全**：AES-256-GCM + PBKDF2-HMAC-SHA256（600k iterations）+ 密码清零 ✅
- **SQL 注入防护**：`text(f'...')` 拼接表名，但表名经 `quote_table` 白名单校验，已标 `# nosec B608` ✅
- 重复目录可能源于重构遗留（`_dir` 后缀暗示"目录式"重构尝试），需确认调用方并删除冗余副本。

### 6.8 风险等级评估
**高**。4090 行重复代码，维护风险大。**建议**：
1. 确认 `orchestration/` 与 `orchestration_dir/` 的调用方，保留其一。
2. 确认 `verify/` 与 `verify_dir/` 的差异点，合并为单一实现。
3. 删除冗余目录，预计可减少 ~4090 行代码。

---

## 七、通知服务（notification / fcm）

### 7.1 文件清单与规模
- `services/notification_service.py`：通知服务
- `services/fcm_service.py`：FCM 推送

### 7.2 代码规范
- 异常处理规范，broad-except 附注释（`# defensive: FCM推送失败不影响事件发布主流程` 等）。

### 7.3 注释覆盖率
- 覆盖良好。

### 7.4 命名合理性
- 命名规范。

### 7.5 圈复杂度
- 适中。

### 7.6 代码重复
- 无明显重复。

### 7.7 潜在缺陷
- **FCM 推送设计良好**：
  - 熔断器机制 ✅
  - 异步推送 ✅
  - 批量限制 500 ✅
  - 凭证非硬编码（从配置读取）✅

### 7.8 风险等级评估
**低**。设计良好。

---

## 风险等级汇总

| 模块 | 风险等级 | 关键缺陷数 | Top 3 问题 |
| --- | --- | --- | --- |
| 1. 核心业务 (dashboard) | 中 | 1 | fetch_mobile_dashboard ~280 行需拆分 |
| 2. 系统管理 (auxiliary/ocr) | 低 | 0 | — |
| 3. 用户管理 (user/auth) | 低 | 0 | — |
| 4. 客户管理 (customer) | 低 | 1 | 手动 LIKE 转义应改用 escape_like |
| 5. 审批管理 (approval) | 低 | 1 | 2 处 multi-sku-order TODO |
| 6. 数据备份 (backup) | 高 | 1 | 4090 行重复代码（orchestration/verify 双副本） |
| 7. 通知服务 (notification/fcm) | 低 | 0 | — |
| **合计** | — | **4** | — |

---

## 高风险模块详细说明

### 6. 数据备份（backup）— 高风险

**问题：4090 行重复代码**

`backup` 包存在两套几乎完全相同的目录结构，疑似重构遗留：

```
fastapi_app/services/backup/
├── orchestration/          # 原实现
│   ├── recovery_test_service.py  (1106 行)
│   ├── policy_service.py         (613 行)
│   └── core.py                   (325 行)
├── orchestration_dir/      # 完全相同的副本
│   ├── recovery_test_service.py  (1106 行)
│   ├── policy_service.py         (613 行)
│   └── core.py                   (325 行)
├── verify/                 # 原实现
│   ├── health_check_service.py   (650 行)
│   ├── query_service.py          (86 行)
│   └── core.py                   (219 行)
└── verify_dir/             # 几乎相同的副本
    ├── health_check_service.py   (650 行)
    ├── query_service.py          (86 行)
    └── core.py                   (219 行)
```

**风险**：
1. 维护成本翻倍：修改一处需同步修改两处，易遗漏。
2. 行为不一致风险：若两副本已悄然分叉，将导致难以排查的 bug。
3. 代码体积虚高：4090 行重复代码占 C 组总行数（20728）的 ~20%。

**重构建议**：
1. **第一步**：使用 `git log` 确认 `orchestration/` 与 `orchestration_dir/`、`verify/` 与 `verify_dir/` 的引入时间与调用方。
2. **第二步**：grep 全仓搜索 `from fastapi_app.services.backup.orchestration_dir` 与 `from fastapi_app.services.backup.verify_dir` 的导入语句。
3. **第三步**：若调用方已统一至单一目录，删除冗余目录；若两目录均有调用方，统一迁移后删除。
4. **第四步**：补充导入测试，确保删除后无残留引用。

---

## 整体改进建议（按优先级）

| 优先级 | 模块 | 建议 | 预期收益 |
| --- | --- | --- | --- |
| P0 | backup | 删除 orchestration_dir/ 与 verify_dir/ 冗余目录 | 减少 ~4090 行重复代码 |
| P1 | dashboard | 拆分 fetch_mobile_dashboard (~280 行) 为多个 _fetch_*_card 子函数 | 单函数 < 60 行，圈复杂度降低 |
| P2 | approval | 排期 multi-sku-order TODO（与 B 组 stock 统一排期） | 多 SKU 计算正确性 |
| P3 | customer | customer_service.py 第 39 行手动 LIKE 转义改用 escape_like | 命名统一，安全防护集中 |

---

## 安全评估汇总

| 维度 | 评估 | 说明 |
| --- | --- | --- |
| 认证授权 | ✅ 良好 | 所有 endpoint 使用 `Depends(get_current_user_id)` 或 `require_permission` |
| 密码存储 | ✅ 优秀 | Argon2id + 时序攻击防护 + 哈希迁移 |
| 备份加密 | ✅ 优秀 | AES-256-GCM + PBKDF2-HMAC-SHA256（600k iterations）+ 密码清零 |
| SQL 注入 | ⚠️ 低风险 | dashboard_service.py f-string 拼接物化视图名（硬编码常量，已标 nosec） |
| 路径遍历 | ✅ 良好 | ocr_service.py 从内存 stream 打开 PDF；ocr_import.py filename 仅用于日志 |
| 命令注入 | ✅ 良好 | 未发现 subprocess / eval / exec 调用 |
| FCM 推送 | ✅ 优秀 | 熔断器 + 异步 + 批量限制 500 + 凭证非硬编码 |
| 异常处理 | ✅ 良好 | broad-except 都有注释说明，无 bare-except，无 except+pass |

---

## 正面发现

1. **认证授权统一**：所有 endpoint 强制认证，权限模型完整。
2. **密码存储达到金融级**：Argon2id + 时序攻击防护 + 哈希迁移，符合 OWASP 2023 推荐。
3. **备份加密设计严谨**：AES-256-GCM + PBKDF2-HMAC-SHA256（600k iterations）+ 密码清零，符合 NIST SP 800-132。
4. **FCM 推送工程化**：熔断器 + 异步 + 批量限制 + 凭证外置，可观测性与可靠性兼备。
5. **异常处理规范**：broad-except 全部附 `# defensive` / `# broad-except` 注释说明容错理由，无 bare-except、无 except+pass。
6. **架构改进落地**：`customer_sampling` 已从 1619 行上帝服务拆分为子包，体现持续重构意识。
7. **SQL 安全边界文档化**：f-string SQL 拼接均附 `# nosec B608` / `# sql-safe` 注释，说明安全边界，便于审查。