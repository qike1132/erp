# ⚠️ 已废弃（Deprecated）——旧迁移脚本，仅供历史参考

本目录（`scripts/migrate/`）是 **2026-08 前后的一次性服务器迁移脚本**，用于当时把生产从旧机搬到新机：

- `export_on_source.ps1` / `build_portable.ps1` —— 源机导出
- `setup_on_target.ps1` / `install_on_target.ps1` —— 目标机装配
- `fix_service_env.ps1` —— 服务环境修补

这些脚本**已被 [`deploy/`](../../deploy/README.md)（离线便携包一键部署）取代**
——`deploy/` 是当前**唯一权威**的部署路径。

**请勿在新部署中使用本目录任何脚本**：它们不反映当前的服务拓扑（五服务）、配置键位与安全基线，
照用来路不明的旧脚本可能产出错误环境。本目录仅为**历史留档**保留，不要作为现行真相引用
（参见 [AGENTS.md](../../AGENTS.md) §6 —— 历史交付物与旧报告的结论可能已过期）。

新服务器部署请走：[`deploy/README.md`](../../deploy/README.md)。
