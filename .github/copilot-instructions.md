# GitHub Copilot 指令 —— 指针

**本项目（滨发协同系统 / binfa-erp）的协作契约在仓库根目录的 `AGENTS.md`，请先完整阅读它。**
本文件不再承载独立规则：历史上它是一份 GraphFlow（MCP 上下文服务）上手指南，且示例用的是**别的项目（游戏前端）**的符号名，与本 ERP 仓库无关，已作废。

本仓库实际是什么（完整版见 `AGENTS.md`）：

- 内网部署的**生产** ERP（采购 / 客户订单 / 库存 / 出货计划 / 生产 / 板房 / 审批 / 备份 / 系统管理）。
- 后端 `fastapi_app/`（FastAPI + PostgreSQL + Redis/ARQ），前端 `frontend-vite/`（Vue 3 + TypeScript + Vite 7，Node >= 22）。
- 生产拓扑：nginx `:3000`（root = `frontend-vite/dist`）→ uvicorn **仅绑** `127.0.0.1:5002`；ARQ worker 独立进程。
- 五道 NSSM 服务：`erp-web`、`erp-prod`、`erp-arq`、`erp-redis`、`erp-redis-broker`；状态以 `logs/prod_runner.json` 为准。
- **这台机器就是生产主机**：没有测试环境，改动直接影响在用业务。
- 提交前跑 `python scripts/quality_gate.py`；提交钩子还包含密钥内容扫描，误报用行尾 `secret-scan:allow <理由>` 抑制。
