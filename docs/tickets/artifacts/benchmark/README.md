# 压测产物目录说明

本目录存放 `scripts/benchmark_compare.py` 产出的压测与对比报告。
`*.json` 已被 `.gitignore` 排除 —— **数字随机器、运行模式、负载变化，不是源码，不要入库**。

---

## 怎么产生可用的前后对比

```bash
# 0) 先确认跑在哪个模式（不同模式的数字不可比！）
python scripts/diag/runtime_mode_probe.py

# 1) 改动前
python scripts/benchmark_compare.py run --label before

# 2) 改代码 …

# 3) 改动后
python scripts/benchmark_compare.py run --label after

# 4) 对比
python scripts/benchmark_compare.py compare \
    --before docs/tickets/artifacts/benchmark/before.json \
    --after  docs/tickets/artifacts/benchmark/after.json
```

默认参数：每端点 60 次 × 3 轮取中位数、并发 8、预热 5。

---

## ⚠️ 本机实测的噪声地台（2026-09-14）

在 dev 单 worker 模式下（`--requests 20 --concurrency 4 --repeat 3`）实测：

| 端点 | P95 | 轮间离散度 |
|---|---:|---:|
| dashboard_stats | 42.2 ms | **56.4%** |
| stock_inventory | 28.8 ms | 24.1% |
| products_list | 27.4 ms | 21.5% |
| purchase_center_orders | 28.7 ms | 17.4% |
| reports_order_logs | 26.4 ms | 16.7% |

**结论：这台机器上 20~45ms 量级的端点，轮间噪声就有 17~56%。**
在这个量级上判定"P95 下降 30%"是没有意义的 —— 噪声比信号大。

因此工具默认 `--min-baseline-ms 50`：基线 P95 低于 50ms 的端点**只报告、不判定**，
避免产出"看起来很漂亮但不可信"的结论。

### 想拿到可判定的数字，需要先把信号抬到噪声之上

- 提高 `--concurrency`（如 32/64），让系统进入真实负载区，P95 会明显上升
- 提高 `--requests`（如 500）让分位数稳定
- 用更接近真实的数据量（空表 vs 数万行，差异是数量级的）
- **必须**在同一运行模式下测 before/after。当前 5002 跑的是 dev 单 worker，
  作为性能基线没有参考价值（见 ITER-3 §0）

### 退出码语义

| 码 | 含义 |
|---|---|
| 0 | 至少一个端点被判定且全部达标 |
| 1 | 有端点未达标 |
| 2 | **不可判定** —— 全部端点的基线低于判定线（噪声主导），或输入文件错误 |

`2` 不是"通过"。把"没测出来"当成"没问题"是最危险的误用。
