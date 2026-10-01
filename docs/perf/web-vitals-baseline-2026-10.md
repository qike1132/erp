# web_vital 真实用户性能基线（2026-10-01）

- 数据来源：生产库 `web_vital` 表（前端 web-vitals 上报，本次为只读分析，未做任何写操作）。
- 样本区间：2026-09-24 ~ 2026-09-30，共 4,147 条上报。
- 指标口径：Google web-vitals；TTFB/LCP/INP 单位为毫秒（ms），CLS 无量纲；rating 为 good / needs-improvement / poor。
- 用途：`docs/optimization-plan-2026-10-01.md` OPT-15（bundle 拆分）的前后对照基线。

## 1. 全站指标分布（P50 / P75 / P95）

| 指标 | 样本数 | P50 | P75 | P95 | good | 需改进 | poor |
|---|---|---|---|---|---|---|---|
| TTFB | 1737 | 23ms | 44ms | 316ms | 1727 | 7 | 3 |
| LCP  | 921  | 711ms | 1.20s | 1.37s | 912 | 5 | 4 |
| CLS  | 834  | 0 | 0 | 0.006 | 832 | 0 | 2 |
| INP  | 655  | 64ms | 88ms | 146ms | 638 | 13 | 4 |

## 2. 上报量 Top 页面

| 页面路径 | 指标种类 | 上报条数 |
|---|---|---|
| /purchase | 4 | 940 |
| /customer-order | 4 | 440 |
| /pattern-room | 4 | 372 |
| /outsource | 4 | 300 |
| /beile-order | 4 | 300 |
| /dashboard | 4 | 270 |
| /stock | 4 | 233 |
| /production | 4 | 132 |
| 127.0.0.1:5173/customer-order（dev 上报混入） | 4 | 128 |
| /purchase-plan | 4 | 123 |
| /material-calculator | 4 | 113 |
| /report | 4 | 97 |

## 3. poor 体验集中点（按条数降序）

| 页面路径 | 指标 | poor 条数 | 该组合 P75 |
|---|---|---|---|
| /pattern-room | LCP | 2 | 12.29s |
| /pattern-room | INP | 2 | 1.06s |
| /customer-order | CLS | 1 | 303ms |
| /customer-order | INP | 1 | 1.23s |
| /login?redirect=/dashboard | LCP | 1 | 196.8s（极端离群，疑为设备休眠唤醒） |
| /pattern-room | CLS | 1 | 264ms |
| /pattern-room | TTFB | 1 | 9.20s |
| /purchase | LCP | 1 | 5.74s |
| / | TTFB | 1 | 2.45s |
| /purchase | TTFB | 1 | 7.77s |
| /backup | INP | 1 | 504ms |

## 4. 结论

1. **真实用户体验优良**：poor 仅 13/4147（0.3%）。LCP P75 = 1.20s（Google 良好阈值 2.5s 内）、INP P75 = 88ms（阈值 200ms 内）、TTFB P75 = 44ms、CLS ≈ 0——**首屏性能当前不是优化重点**，OPT-15（bundle 拆分）按"低成本顺手做"对待即可，不必抢优先级。
2. 相对弱项集中在 **/pattern-room（板房）**：LCP 与 INP 的 poor 记录最多，且 P75 达 12.3s/1.06s——大图/表格交互重的页面，若后续要优化前端性能，从这里开始。
3. 数据卫生两项小问题：① dev server（127.0.0.1:5173）的上报混入了生产表（128 条），建议上报端按 host 过滤或加环境标记；② `/login` 存在 196.8s 的极端 LCP 离群值（设备休眠唤醒类），分析时建议按 P95 截断。
