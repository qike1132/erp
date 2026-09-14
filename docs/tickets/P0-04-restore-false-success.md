# P0-04　数据库恢复失败仍返回成功（灾备静默失效）

| 字段 | 值 |
|---|---|
| 严重度 | 🔴 高（数据安全 · 静默失败） |
| 类型 | 缺陷 · 错误处理 |
| 模块 | `scripts/database/db_manager.py` |
| 预估工时 | 30 min |
| 批次 | A |
| 依赖 | 无 |

## 现象

灾难恢复 / 恢复演练执行后**报告"恢复成功"**，但数据库实际为空或只恢复了一部分。
由于返回 `True`，调用方（含 CLI `main()` → `sys.exit(0)`）与上层备份编排都认为流程正常，
**不会有任何告警** —— 等到真正需要数据时才发现备份恢复不可用。

这是本批 P0 中**唯一会直接导致数据丢失且无法事后补救**的一项。

## 定位

`scripts/database/db_manager.py:380-411`（`restore_postgresql`）

```python
        # Restore
        self.log("恢复数据库中...")
        try:
            with open(backup_file, 'rb') as f:
                result = subprocess.run([
                    'psql', '-h', config['host'], '-p', config['port'],
                    '-U', config['user'], '-d', config['database'],
                    '-v', 'ON_ERROR_STOP=0',                      # ← 关键问题 1
                ], stdin=f, capture_output=True, env=env, timeout=600)

            stderr_text = result.stderr.decode('utf-8', errors='replace')

            if result.returncode != 0:
                # psql often returns non-zero for minor warnings - log but don't fail   ← 认知错误
                warning_lines = [
                    line for line in stderr_text.split('\n')
                    if 'ERROR' in line and 'already exists' not in line.lower()
                ]
                if warning_lines:
                    self.log(f"恢复过程中有 {len(warning_lines)} 个错误", 'WARNING')
                    for line in warning_lines[:10]:
                        self.log(f"  {line.strip()}", 'WARNING')
                else:
                    self.log(f"恢复完成（有非关键警告: {stderr_text[:200]}）", 'WARNING')

            return True, "PostgreSQL 数据库恢复完成"                  # ← 关键问题 2：无条件 True
```

上游 `:365-376` 已经 `DROP DATABASE` + `CREATE DATABASE`，**所以"恢复失败"意味着库是空的**：

```python
            subprocess.run([
                'psql', ..., '-c', f'DROP DATABASE IF EXISTS "{config["database"]}";',
            ], env=env, capture_output=True, check=True, timeout=30)
            subprocess.run([
                'psql', ..., '-d', 'postgres',
                '-c', f'CREATE DATABASE "{config["database"]}" OWNER "{config["user"]}";',
            ], env=env, capture_output=True, check=True, timeout=30)
```

## 根因

两层问题叠加：

1. **`ON_ERROR_STOP=0`** —— psql 在脚本中遇到错误时**继续执行**并**以 0 退出**。
   因此 `result.returncode != 0` 这个判断本身就**几乎永不成立**，
   于是即便 SQL 全部失败也走不到 `if` 块，直接 `return True`。
   （`ON_ERROR_STOP=1` 时，脚本出错 psql 以 3 退出。）
2. **无条件 `return True`** —— 即使 `returncode != 0` 成立（如连接问题），也只打 WARNING，最后仍返回成功。

代码注释 `# psql often returns non-zero for minor warnings - log but don't fail` 反映了一个**认知错误**：
psql 的退出码语义并非"小警告也给非零"。真正的小警告（如 `NOTICE`）不改变退出码，
反而是**真错误被 `ON_ERROR_STOP=0` 吞掉**。

> 补充：`'already exists' not in line.lower()` 这个过滤是本末倒置的 ——
> 它把 "already exists" 当噪音放过，但 `DROP DATABASE` + `CREATE DATABASE` 是全新空库，
> 正常恢复**不应该**出现任何 `already exists`。出现即说明流程有异常，应当报告而非忽略。

## 修复方案

```diff
--- a/scripts/database/db_manager.py
+++ b/scripts/database/db_manager.py
@@
                 result = subprocess.run([
                     'psql', '-h', config['host'], '-p', config['port'],
                     '-U', config['user'], '-d', config['database'],
-                    '-v', 'ON_ERROR_STOP=0',
+                    '-v', 'ON_ERROR_STOP=1',
                 ], stdin=f, capture_output=True, env=env, timeout=600)
 
             stderr_text = result.stderr.decode('utf-8', errors='replace')
 
-            if result.returncode != 0:
-                # psql often returns non-zero for minor warnings - log but don't fail
-                warning_lines = [
-                    line for line in stderr_text.split('\n')
-                    if 'ERROR' in line and 'already exists' not in line.lower()
-                ]
-                if warning_lines:
-                    self.log(f"恢复过程中有 {len(warning_lines)} 个错误", 'WARNING')
-                    for line in warning_lines[:10]:
-                        self.log(f"  {line.strip()}", 'WARNING')
-                else:
-                    self.log(f"恢复完成（有非关键警告: {stderr_text[:200]}）", 'WARNING')
-
-            return True, "PostgreSQL 数据库恢复完成"
+            error_lines = [
+                line for line in stderr_text.split('\n')
+                if line.strip().startswith('ERROR') or 'ERROR:' in line
+            ]
+
+            # psql 退出码：0=正常，1=自身致命错误，2=连接中断，3=脚本错误(需 ON_ERROR_STOP=1)
+            if result.returncode != 0 or error_lines:
+                detail = error_lines[0].strip() if error_lines else stderr_text.strip()[:200]
+                self.log(
+                    f"数据库恢复失败（psql 退出码={result.returncode}，"
+                    f"错误行数={len(error_lines)}）: {detail}",
+                    'ERROR',
+                )
+                for line in error_lines[1:10]:
+                    self.log(f"  {line.strip()}", 'ERROR')
+                return False, f"PostgreSQL 恢复失败：{detail}"
+
+            self.log("PostgreSQL 数据库恢复完成")
+            return True, "PostgreSQL 数据库恢复完成"
```

**加固建议（强烈推荐，2 行）** —— 恢复完成后校验库非空。
"psql 退出码为 0" 不等于"数据真的进去了"（例如 dump 文件本身是空的）：

```python
            # 数据落地校验：至少要有业务表
            verify = subprocess.run([
                'psql', '-h', config['host'], '-p', config['port'],
                '-U', config['user'], '-d', config['database'],
                '-tAc', "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema='public';",
            ], env=env, capture_output=True, timeout=30)
            table_count = int((verify.stdout or b'0').strip() or 0)
            if table_count == 0:
                return False, "PostgreSQL 恢复后 public schema 无任何表，疑似恢复失败"
            self.log(f"恢复完成，public schema 表数={table_count}")
```

## 验收标准

1. **失败必须失败**（核心断言）——用损坏/空的 dump 文件验证：
   ```bash
   echo "THIS IS NOT SQL" > /tmp/broken.sql
   python scripts/database/db_manager.py restore /tmp/broken.sql   # 或对应 CLI 入口
   echo "exit=$?"      # 期望 非 0
   ```
   修复前：exit=0 且打印"恢复完成"；修复后：exit≠0 且打印 ERROR 详情。
2. `ON_ERROR_STOP=1` 已生效
   ```bash
   grep -n "ON_ERROR_STOP" scripts/database/db_manager.py     # 期望仅剩 =1
   ```
3. **正常恢复仍成功** —— 拿一份真实备份跑一次完整恢复演练，期望返回 True 且表数 > 0。
   （必须在非生产库或已有备份保护的环境执行。）

## 发布动作

`scripts/database/db_manager.py` 属于运维脚本，**不随 FastAPI 进程加载**，
因此**无需重启 `erp-prod`**，改动即刻生效（下次执行恢复时）。

## 回归风险

中 —— 本工单把"宽松通过"改成"严格失败"，**可能让原本"看起来成功"的恢复流程开始报错**。
这是**预期行为**（那些恢复本来就是失败的），但会改变运维体感。

因此上线前必须先做一次真实恢复演练：
- 若演练报错 → 说明历史恢复一直是坏的，需进一步查 dump 文件本身
- 若演练通过 → 直接上线

**切勿在未演练的情况下直接用于真实灾备场景。**

## 关联

同一函数族内还有 2 项低优先级问题（见报告 F9），建议本工单顺手处理：
- `db_manager.py:289-303`：`verify` 为读前 100KB 却把 GB 级 `.gz` **完整解压落盘**
- `db_manager.py:344-349`：`pre_backup_dir / f'pre_restore_{ts}.sql'` 是**丢弃结果的无效表达式**；
  `pre_restore` 目录不在 `self.backup_dirs` 中 → `cleanup()` 永不清理，每次恢复都残留一份未压缩全量备份
