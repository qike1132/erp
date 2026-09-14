# ITER-1　备份链路契约：`bytes` → `Path`（流式化）

| 字段 | 值 |
|---|---|
| 迭代目标 | 让备份/恢复链路在**任何数据量下内存占用有界**，消除 4 项 OOM 风险 |
| 优先级 | P1-1（最高杠杆） |
| 预估 | 1 个迭代（3–5 个工作日） |
| 涉及模块 | `services/backup/`（orchestration / json_backup / format_strategy / crypto / records）、`api/v1/endpoints/backup/`、`tasks/backup_tasks.py` |
| 前置依赖 | 无（与 ITER-2 可并行） |
| 风险等级 | 中高（触及数据安全主链路，必须有恢复演练兜底） |

---

## 一、为什么这是最高杠杆的一处改动

### 1.1 一个错误契约，四处 OOM

`create_full_backup()` 的返回类型是 `bytes`。这个契约像血管一样贯穿整条备份链路，
导致**所有下游都必须把整包数据拿在手里**：

| 位置 | 症状 | 推演（20 GB 逻辑数据） |
|---|---|---|
| `orchestration/core.py:304-317,392,408-418` | ZIP 同步构建 + `read_bytes()` + AES-GCM 加密各持一份 | 峰值 ≈ 3N ≈ **60 GB RSS → 必 OOM** |
| `json_backup.py:336-354`（pg_dump 不可用时的**兜底路径**） | 全表 dict → `json.dumps` 字符串 → `encode` bytes，三份副本 | 峰值 ≈ 3N ≈ **60 GB** |
| `format_strategy.py:259-268`（`inspect()` 只为读 manifest） | 合并全部 chunk + 全量解密 | 峰值 ≈ 3N |
| `orchestration/core.py:239-240`（`sha256_file`） | 虽分块读，但**同步**执行 | 事件循环冻结 **25–70 s** |

**关键洞察**：这四处不是四个独立缺陷，而是**同一个契约的四个表现**。
把接口从 `-> bytes` 改成 `-> Path`（临时文件），四处同时消解。

### 1.2 当前数据量为什么还没爆

实测备份包约 8 MB —— 所以问题**尚未在生产暴露**。
这意味着：本迭代是**预防性改造**，有充分的时间窗口，不必冒险。

但反过来，一旦数据量上来（图纸/面辅料大样图、历史订单累积），
OOM 会以"备份任务突然失败 + 服务内存暴涨"的形式出现，届时排障成本极高。

### 1.3 当前正确的部分（改造时应参照）

`api/v1/endpoints/backup/export.py:142-146` 的 ZIP 路径**已经用了流式实现**：

```python
# export.py 中已有正确范例
await backup_service.create_full_backup_to_file(...)
```

即**项目里已经存在正确做法，只是没有统一**。
本迭代的目标就是"把少数正确路径推广为唯一路径"。

---

## 二、目标设计

### 2.1 契约变更

```python
# 变更前
async def create_full_backup(...) -> tuple[bytes, dict]: ...

# 变更后
async def create_full_backup_to_file(...) -> tuple[Path, dict]:
    """返回落盘文件的路径，调用方负责在消费后删除临时文件"""
```

**三条硬约束**：
1. 全链路**不得出现 `read_bytes()` / `read()` 无参调用**
2. 加密必须**分块流式**（不得先 `read_bytes` 再 `encrypt`）
3. 所有哈希/压缩/加密的同步段必须包 `asyncio.to_thread`

### 2.2 分层改造策略（关键：如何做到可回滚）

**不要一次性替换**。采用"并存 → 切换 → 删除"三步：

```
阶段 A（本迭代第 1–2 天）
  ├─ 新增 *ToFile 变体（流式实现），保留原 bytes 版本不动
  ├─ 两者共用同一套底层：导出 → 打包 → 加密，由 writer 注入
  └─ 新增流式单元测试 + 内存上界测试

阶段 B（第 3–4 天）
  ├─ 逐个把调用方切到 *ToFile（每次一个 commit，可单独回滚）
  ├─ 调用方负责 tmp 文件生命周期（with contextlib.closing / try-finally）
  └─ bytes 版本标记 @deprecated 并打 warning 日志（观察是否还有残留调用）

阶段 C（第 5 天）
  ├─ 删除 bytes 版本
  ├─ 全仓 grep 确认无残留
  └─ 完整备份+恢复演练
```

### 2.3 统一的流式写入抽象

```python
# services/backup/_stream.py（新增）
from contextlib import contextmanager

@contextmanager
def atomic_output(target: Path):
    """写临时文件 → 成功后原子改名（同时解决 P1-13 的"清理撞上正在写的备份"）

    统一 .tmp 后缀，使清理任务只匹配正式文件名，天然避开写入中的文件。
    """
    tmp = target.with_suffix(target.suffix + '.tmp')
    try:
        with open(tmp, 'wb') as f:
            yield f
        os.replace(tmp, target)      # 原子
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
```

**注意**：这个 `atomic_output` 顺带解决了 **P1-13**（清理与备份并发导致删除正在写的文件）。
建议 ITER-1 一并落地，因为它们是同一处代码的两次改动，分开做等于改两遍。

### 2.4 流式加密

```python
# 变更前（crypto.py 内，一次吃下整个 bytes）
encrypted_bytes = aesgcm.encrypt(nonce, zip_bytes, None)

# 变更后：分块 AEAD（每块独立 nonce，块头记录块序号防重排）
CHUNK = 4 * 1024 * 1024
def encrypt_stream(src: Path, dst: Path, key: bytes) -> dict:
    with open(src, 'rb') as fin, atomic_output(dst) as fout:
        idx = 0
        for chunk in iter(lambda: fin.read(CHUNK), b''):
            nonce = os.urandom(12)
            ct = AESGCM(key).encrypt(nonce, chunk, str(idx).encode())
            fout.write(len(nonce).to_bytes(1, 'big') + nonce + ct)
            idx += 1
        ...
```

> ✅ **决策已拍板（2026-09-13 00:38，用户）：接受「新写用分块格式，读取时兼容旧格式」。**
>
> **落地状态（见 `ITER-0-decision-verification.md`）**：三项要求**均已实现并接入主链路** ——
>
> | 要求 | 实现 |
> |---|---|
> | 保留旧格式只读解密 | `decrypt_stream`（`core/backup_encryption.py:373`）自动识别 |
> | manifest 标记 `encryption_mode` | `'chunked-v1'`（`encrypt_stream` L362） |
> | 用现网真实加密备份验证 | ⚠️ **尚未做**（见下） |
>
> 格式判定 `detect_encryption_format(head)` → `'chunked-v1' | 'plaintext' | 'legacy'`；
> magic `b'BFBKENC1'`；块序号经 `_chunk_aad(header, index)` 进 AAD 防重排；
> `chunked_encryption_enabled()` 提供一键回退。测试 `test_backup_encryption_stream.py` → 32 passed。
>
> 🔴 **唯一遗留风险**：§4.2 要求的「用**现网真实**加密备份验证旧格式仍可解密恢复」尚未执行。
> 单测覆盖的是构造样本，不等于现网历史备份。上线前必须补这一步。

---

## 三、任务拆解

| # | 任务 | 产出 | 预估 | 依赖 |
|---|---|---|---|---|
| T1 | **调用方清单**：全仓找 `create_full_backup` / `read_bytes` / `to_bytes` 的调用点，输出表格（文件:行 / 用途 / 是否可流式） | `docs/tickets/iterations/ITER-1-callers.md` | 2 h | — |
| T2 | 新增 `_stream.py::atomic_output` | 工具 + 单测 | 3 h | — |
| T3 | 新增 `crypto.encrypt_stream` / `decrypt_stream`，保留旧解密路径 | 加密模块 + 兼容测试 | 1 d | T2 |
| T4 | 新增 `json_backup.export_to_file()`（逐表 `json.dump(..., f)`，每表 `del rows`） | 流式导出 | 1 d | T2 |
| T5 | 新增 `orchestration.create_full_backup_to_file()`（组合 T2–T4） | 主链路流式化 | 1 d | T3,T4 |
| T6 | `sha256_file` 调用处加 `asyncio.to_thread` | 事件循环解冻 | 2 h | — |
| T7 | `format_strategy.inspect()` 改为只读 manifest（不合并全 chunk、不解密全部） | 列表/校验零开销 | 4 h | T2 |
| T8 | 调用方逐一切换（export.py / tasks / export_legacy / save 等） | 每次一个 commit | 1 d | T5 |
| T9 | 备份后**立即**校验文件大小 + 表数（防流式写入静默截断） | 完整性守卫 | 3 h | T5 |
| T10 | 内存上界测试 + 完整备份/恢复演练 | 报告 | 0.5 d | T8 |

---

## 四、验收标准

### 4.1 硬性断言（可自动化）

```python
@pytest.mark.asyncio
async def test_backup_memory_bounded(monkeypatch):
    """20 GB 级数据下，备份进程 RSS 增长必须 < 500 MB"""
    import resource, tracemalloc
    tracemalloc.start()
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    await create_full_backup_to_file(...)          # 用大表夹具
    after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    assert (after - before) < 500 * 1024, '备份链路仍在全量进内存'
```

| 断言 | 期望 |
|---|---|
| 全链路无 `read_bytes()` / 无参 `read()` | `grep -rn "read_bytes()\|\.read()" services/backup/` → 仅白名单（`decrypt_stream` 的分块读） |
| 同步 IO 全在 to_thread | 人工审查 T6/T5 的 `await asyncio.to_thread` 覆盖率 |
| 旧加密备份可解密 | 用现网真实 `.zip.enc` 跑一次恢复 → 数据一致 |
| 备份耗时 | 不得比改造前**劣化 > 20%**（流式可能略慢，需量化） |

### 4.2 恢复演练（本迭代的出口条件，不可跳过）

按项目既有做法：
1. 触发一次全量备份 → 记录文件大小、表数、行数指纹
2. **停生产服务**（管理员操作）→ 从该备份恢复 → 校验
3. 校验项：表数一致、关键表行数一致、抽样数据指纹一致、`public schema` 非空
4. 记录 RSS 峰值与耗时

> 参照 P0-04：恢复流程必须能**正确报告失败**。若 P0-04 尚未落地，本迭代的演练结论不可信
> —— **建议 P0-04 先于本迭代完成**。

---

## 五、风险与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| 加密格式变更导致**旧备份无法恢复** | 🔴 高 | 保留 legacy 只读解密路径 + manifest 标记 + 用现网真实备份回归 |
| 流式写入**静默截断**（写一半没报错） | 🔴 高 | T9 完整性守卫：写完后校验文件大小 + zip 可打开 + 表数非 0 |
| 临时文件残留占满磁盘 | 🟡 中 | `atomic_output` 的 `except` 分支删除；启动时清扫 `*.tmp` |
| 调用方漏改导致 bytes 版本仍被使用 | 🟡 中 | 阶段 B 给 bytes 版本加 `@deprecated` + warning 日志，观察一个迭代后删除 |
| 改造期间备份失败影响生产 | 🟡 中 | 逐 commit 灰度；保留 feature flag `BACKUP_STREAMING_ENABLED` 可一键回退 |

---

## 六、交付物

- `services/backup/_stream.py`（新增，`atomic_output`）
- `crypto.py` / `json_backup.py` / `orchestration/core.py` / `format_strategy.py`（流式改造）
- `docs/tickets/iterations/ITER-1-callers.md`（调用方清单，T1）
- 内存上界测试 + 恢复演练报告
- 顺带关闭 **P1-13**（清理并发保护，共用 `atomic_output`）

## 七、为什么值得排一个完整迭代

- **收益确定性高**：把"20 GB 数据必 OOM"变成"内存有界"，是**能力边界**的改变，不是优化百分比
- **改动面收敛**：本质是**一个契约变更**，而非几十处独立修补
- **顺带收益**：一并解决 P1-13（清理并发）、P1-5（巡检全量读），因为都落在同一批文件
- **窗口期充裕**：当前备份仅 8 MB，没有生产压力，可以稳妥分阶段做
