# JWT 密钥目录（Windows / NSSM 部署）

本目录存放 JWT 签名相关文件。**私钥严禁提交到版本库。**

## 当前生产形态（2026-10 起）

- 部署方式：Windows 本机 + NSSM 服务（**不是** Docker/K8s）。
- 生产签名钥：`_ops/credentials/` 下的私钥文件（由部署流程放置），
  通过环境变量 `JWT_PRIVATE_KEY_PATH` 指向；运行时实际生效的是轮换后的
  **v2 私钥**（历史 `private.pem` 已退役，勿再使用）。
- `public.pem` 可提交，用于校验。
- 私钥文件权限由 `.gitignore` + `.githooks` 密钥扫描双重拦截。

## 轮换步骤（摘要）

1. 生成新密钥对（openssl 或项目脚本）。
2. 将新私钥放入受控目录，更新 `JWT_PRIVATE_KEY_PATH`。
3. 重启 `erp-prod` / `erp-arq`（重启前确认工作区在 main，见 AGENTS.md §6.1）。
4. 保留旧公钥直到所有旧 token 过期。

> 2026-10-17 审计 P2-79：本文件此前是 Docker/K8s 时代的过期文档（Secret volume
> 挂载 / `docker run -v`），与当前 NSSM 部署不符，已按实际形态改写。
