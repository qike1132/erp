# GEMINI.md —— 指针

**本项目（滨发协同系统 / binfa-erp）的协作契约在 `AGENTS.md`，请先完整阅读它。**
本文件不再承载独立规则：历史上它是一份 GraphFlow 工具上手指南（含 GRAPHFLOW 托管块），与 ERP 项目无关，已作废。

关键前提（详见 `AGENTS.md`）：这是**内网生产** ERP（FastAPI + PostgreSQL + Redis/ARQ，前端 Vue 3 + Vite 7），
**当前机器同时是生产主机与运维主机**，没有测试环境。解析 Python 结构必须用 `ast`；生产拓扑与红线见 `AGENTS.md`。
