# P0-10　WAL 备份伪实现（返回不存在的文件、恢复直接报成功）

| 字段 | 值 |
|---|---|
| 严重度 | 🟡 中（**潜伏**：当前无调用方，但对外暴露为可用能力） |
| 类型 | 缺陷 · 数据安全语义 |
| 模块 | `fastapi_app/services/backup/snapshot.py`、`services/backup/incremental.py` |
| 预估工时 | 30 min |
| 批次 | A |
| 依赖 | 无 |

## ⚠️ 分类修正（复核后判定为"潜伏"）

复核结论：**该能力当前不可达** ——

```bash
grep -rni "wal_incremental\|binary_log" fastapi_app/api/     # → 无输出（无路由）
grep -rni "wal\b\|二进制日志" frontend-vite/src               # → 无输出（无前端入口）
```

真实在用的增量备份走的是另一条实现：

```
POST /save-incremental            → export.py:347
                                   → backup_service.create_incremental_backup()   # incremental.py:34（真实实现）
ARQ 自动增量备份任务              → tasks/backup_tasks.py:183 / :644  → 同上
```

而本工单涉及的 `create_binary_log_backup` / `restore_from_binary_log` / `create_wal_incremental_backup`
**仅被 `services/backup/__init__.py:223/230/261` 导出**。

> **⚠️ 事实更正（2026-09-12 执行时复核发现）**
> 原文写"无任何调用方"，**不准确**：`services/backup/incremental.py:28` 导入了 `create_binary_log_backup`，
> 并在 `:206` 实际调用它（其上游 `create_wal_incremental_backup` 自身确实零调用方）。
> 该调用点**不在任何 try 块内**，因此让 `create_binary_log_backup` 抛错会自然向上传播 —— 无需在
> `incremental.py` 增补 try/except，反而更稳（返回 `{'success': False}` 依赖调用方检查 `success`，
> 而这正是本缺陷家族的成因）。据此执行时**有意偏离了下面的方案 A 片段**：
> 未保留 60 行死原型代码（避免被"取消注释"重新引入缺陷），改由文档串说明待实现路径。

**那为什么仍要修**：它的失败模式是"**在灾备场景下返回成功但什么都没做**"。
这类函数一旦被人在紧急时刻从 facade 里翻出来用（`backup_service.restore_from_binary_log(...)`），
会得到 `success: True`，从而**误判已具备 PITR 恢复能力** —— 这是最危险的一类错误：假成功比失败更危险。

结论：严重度按"潜伏隐患"定级 🟡，但因修复只需 30 分钟且失效模式不可接受，仍排入 P0 批次。

## 定位

### 缺陷 1：`create_binary_log_backup` 返回一个从未创建的文件

`fastapi_app/services/backup/snapshot.py:130-207`

```python
async def create_binary_log_backup(db, start_lsn=None, output_dir=None) -> dict:
    ...
        # 使用 pg_basebackup 创建基础备份（如果需要）
        # 或者使用 pg_receivewal 接收 WAL 日志
        # 这里我们使用 pg_dump 的逻辑，但实际应该使用 pg_basebackup 或 pg_receivewal

        # 暂时实现为创建包含 WAL 信息的元数据文件      # ← L180 自述"暂时实现"
        backup_info = {
            'type': 'binary_log',
            'start_lsn': start_lsn,
            'end_lsn': current_lsn,
            'wal_info': wal_info,
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'backup_file': str(backup_file),          # ← 指向从未写入的路径
        }

        info_file = output_dir / f'wal_backup_{timestamp}.json'
        info_file.write_text(json.dumps(backup_info, indent=2, ensure_ascii=False))

        return {
            'success': True,                          # ← 报成功
            'backup_file': str(backup_file),          # ← wal_backup_xxx.tar.gz，文件不存在
            ...
        }
```

其中 `backup_file` 只在 `:156` 被赋值（拼路径），**全程没有任何 `write` / `tarfile` / `pg_basebackup` 调用**：

```python
# snapshot.py:156
backup_file = output_dir / f'wal_backup_{timestamp}.tar.gz'
```

### 缺陷 2：`restore_from_binary_log` 不做事却报成功

`fastapi_app/services/backup/snapshot.py:210-258`

```python
        target_lsn = target_lsn or end_lsn
        logger.info(f"从二进制日志备份恢复: 从 LSN {start_lsn} 到 {target_lsn}")

        # 这里应该实现实际的 WAL 恢复逻辑
        # 实际实现需要使用 pg_restore 或类似的工具

        # 暂时返回成功信息                          # ← L247
        return {
            'success': True,                         # ← 完全没做恢复
            'message': f"二进制日志恢复已计划: 从 {start_lsn} 到 {target_lsn}",
            ...
        }
```

### 传导：增量备份把该结果当成功落库

`fastapi_app/services/backup/incremental.py:206-212`

```python
    wal_backup_result = await create_binary_log_backup(
        db=db, start_lsn=start_lsn, output_dir=BACKUP_DIR / 'wal_incremental'
    )
    # 创建备份元数据
    backup_info = {'version': BACKUP_FORMAT_VERSION, 'type': 'wal_incremental', ...}
    ...
    return {'success': True, ...}
```

## 修复方案（二选一，**推荐方案 A**）

### 方案 A：显式声明未实现（推荐，30 min）

原则：**宁可明确报错，不可静默假成功**。

```diff
--- a/fastapi_app/services/backup/snapshot.py
+++ b/fastapi_app/services/backup/snapshot.py
@@
 async def create_binary_log_backup(
     db: AsyncSession,
     start_lsn: str | None = None,
     output_dir: Path | None = None,
 ) -> dict:
     """创建基于 PostgreSQL WAL 的二进制日志备份
+
+    ⚠️ 尚未实现（P0-10）。
+    当前无 pg_basebackup / pg_receivewal 调用，因此**无法产出可恢复的 WAL 归档**。
+    此前实现会返回 success=True 但 backup_file 指向一个从未创建的文件，
+    在灾备场景下会误导运维认为已具备 PITR 能力。现改为显式抛错。
 
     Args:
     ...
     Returns:
         包含备份信息的字典
+
+    Raises:
+        BinaryLogError: 该功能尚未实现
     """
+    raise BinaryLogError(
+        'WAL 二进制日志备份尚未实现（缺少 pg_basebackup / pg_receivewal 集成）。'
+        '如需时间点恢复（PITR），请先完成实现；当前请使用全量备份 + 增量备份。'
+    )
+    # 以下为待实现的原型代码，保留以说明设计意图：
     try:
@@
 async def restore_from_binary_log(
     db: AsyncSession,
     backup_info_file: Path,
     target_lsn: str | None = None,
 ) -> dict:
     """从二进制日志备份恢复
+
+    ⚠️ 尚未实现（P0-10）。此前会返回 success=True 但**不执行任何恢复动作**，
+    属"假成功"，已改为显式抛错。
 
     Args:
     ...
     Returns:
         恢复结果字典
+
+    Raises:
+        BinaryLogError: 该功能尚未实现
     """
+    raise BinaryLogError(
+        'WAL 二进制日志恢复尚未实现。此前该函数返回成功但不执行任何恢复，'
+        '现已改为显式报错以免误判灾备能力。'
+    )
     try:
```

同时 `incremental.py:206` 的调用点改为捕获并明确失败（不再落库成功）：

```diff
-    wal_backup_result = await create_binary_log_backup(
-        db=db, start_lsn=start_lsn, output_dir=BACKUP_DIR / 'wal_incremental'
-    )
+    try:
+        wal_backup_result = await create_binary_log_backup(
+            db=db, start_lsn=start_lsn, output_dir=BACKUP_DIR / 'wal_incremental'
+        )
+    except BinaryLogError as e:
+        logger.warning('WAL 增量备份不可用，回退到逻辑增量备份: %s', e)
+        return {'success': False, 'error': str(e), 'type': 'wal_incremental'}
```

**并从公开 facade 中摘除**，避免被误当作可用能力：

```diff
--- a/fastapi_app/services/backup/__init__.py
+++ b/fastapi_app/services/backup/__init__.py
@@
-    "create_binary_log_backup",
+    # "create_binary_log_backup",   # P0-10：未实现，已摘除出公开 API
@@
-    "create_wal_incremental_backup",
+    # "create_wal_incremental_backup",   # P0-10：未实现，已摘除出公开 API
@@
-    "restore_from_binary_log",
+    # "restore_from_binary_log",   # P0-10：未实现，已摘除出公开 API
```

> 注意：从 `__all__` 摘除不等于删除函数。这样既阻断误用，又保留实现位置供后续开发。
> 若有 UI/文档宣称支持 PITR，本工单需一并更正文案。

### 方案 B：真正实现（约 2–3 天，本工单不做）

需要 `pg_basebackup -D <dir> -Ft -z` 做基础备份 + `pg_receivewal` 归档 WAL +
恢复时的 `recovery.signal` / `restore_command` 配置。属于独立的备份能力建设，应单独立项。

## 验收标准

1. **不再假成功**
   ```python
   @pytest.mark.asyncio
   async def test_binary_log_backup_raises_not_implemented(db):
       from fastapi_app.services.backup.snapshot import create_binary_log_backup
       from fastapi_app.services.backup.exceptions import BinaryLogError
       with pytest.raises(BinaryLogError, match='尚未实现'):
           await create_binary_log_backup(db)
   ```
2. **facade 不再对外声明**
   ```bash
   C:/Users/Administrator/AppData/Local/Programs/Python/Python313/python.exe -c "
   from fastapi_app.services import backup
   for n in ('create_binary_log_backup','create_wal_incremental_backup','restore_from_binary_log'):
       print(n, 'in __all__ =', n in backup.__all__, '| attr =', hasattr(backup, n))"
   ```
   期望 `__all__` 三个均为 `False`。
   **⚠️ 诚实说明（执行时实测）**：`__init__.py` 用 `from .snapshot import *`，
   因此三者的**模块属性仍然存在**（`backup_service.create_binary_log_backup` 依旧可调用）。
   摘除 `__all__` 属**命名卫生与意图声明，并非硬阻断** —— 真正的阻断来自函数体第一行的 `raise`。
3. **执行时的实测结果（2026-09-12）**
   ```
   PASS create_binary_log_backup -> WAL 二进制日志备份尚未实现（缺少 pg_basebackup / pg_receivewal 集成）…
   PASS restore_from_binary_log  -> WAL 二进制日志恢复尚未实现。此前该函数返回成功但不执行任何恢复…
   __all__：三者均 False
   ruff fastapi_app/services/backup/snapshot.py → All checks passed（含既有 F401 asyncio 一并清除）
   ```
4. **真实增量备份不受影响**（回归）
   ```bash
   C:/Users/Administrator/AppData/Local/Programs/Python/Python313/python.exe -m pytest \
     tests/test_backup_p0_p1_p2.py fastapi_app/tests/test_backup.py -q
   ```
   > 路径更正：`test_backup_p0_p1_p2.py` 在 **`tests/`** 下，不在 `fastapi_app/tests/`（原文写错）。
   `POST /save-incremental` 仍应正常工作（走 `create_incremental_backup`，未被本工单触及）。
   实测 `test_backup.py` 42 passed；
   `test_backup_m1/m2` 的 3 项失败经 stash 回滚取证为**既有失败**（ARQ 未运行 + 夹具 Mock/AsyncMock 问题）。

## 发布动作

改动 `services/backup/snapshot.py` / `incremental.py` / `__init__.py`（进程内模块）
→ **必须重启 `erp-prod`**。

## 回归风险

低。三个函数当前无调用方，改动不会影响在用的备份流程。
唯一需确认的是 `__init__.py` 的 `__all__` 摘除不会让某个 `from ... import *` 或动态导入失败
（验收项 2/3 已覆盖）。

## 后续建议

1. **文档对齐**：检查运维手册 / UI 文案是否宣称"支持时间点恢复（PITR）"，
   若有需同步更正为"暂不支持"——**这是本工单真正的价值所在**
2. 若 PITR 是业务刚需，单独立项实现（方案 B），并纳入灾备演练清单
