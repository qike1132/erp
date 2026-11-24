# ERP Windows 离线便携包

**当前安装未放行，仅允许在全新、隔离的 Windows 目标机运行 `-PreflightOnly`。** 应用迁移及种子脚本的数据库连接隔离、安装失败恢复和回切尚未实机证明，安装入口默认拒绝且不能进入建库、迁移或发服务。它不是原地升级、断点续装或生产回切工具；`-Force`、`-AllowDropDatabase`、`-SkipVerify` 仍会被拒绝。常规部署及其回切见[部署手册](../docs/PROJECT_MANUAL.md)。

## 1. 构建

使用 **64 位 Windows PowerShell 5.1**。须批准从源环境读取 `.env`、应用私钥、上传文件及真实数据库；即使 `pg_dump` 只读，也会接触生产数据。本仓的共用生产主机不是安装/恢复演练环境。

- 从干净的 `main` 构建。准备本机 Python 3.13、PostgreSQL 客户端、前端 `dist`、JWT 私钥与上传签名配置。构建脚本会从哈希锁安装 Python 依赖；如禁止访问外网，预先配置可信离线 wheel 源。
- `-OutDir` 是已由管理员创建并控制权限的本机 NTFS **发布目录**（默认 `D:\erp_portable`），须与源树分离，不得使用链接或共享目录。脚本不覆盖或递归删除该目录。
- 默认交互式隐藏输入包口令；不接受明文口令参数。`-SkipZip` 已禁用；`-DryRun` 只做前置检查，不连库、不组装、不写文件，不等于构建或安装验收。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy\build_package.ps1 -OutDir D:\erp_portable
```

构建与安装均在 `%ProgramData%\erp-stage-<随机 ID>` 使用专用 NTFS ACL 暂存（仅当前执行身份、Administrators 和 SYSTEM）。常规成功/失败会清理本次目录；清理失败会报错并给出位置，须隔离残留并由有权限的运维人工处理。断电、强制退出仍可留下该目录；这不是存储介质安全擦除，敏感场景须使用加密卷，监控残留，不得按名称通配符批量删除。

发布目录只交付 `.tar.gz.enc` 和其 `.sha256` 旁车。便携包含业务凭据和数据（应用 `.env`、JWT 私钥、上传签名、数据库导出和上传文件），**不携带源机 TLS 材料或第三方安装器**。按照迁移审批设定保留期限及处置方式，勿传公网、勿把口令和包同路传输。

## 2. 独立验明发布来源

通过已认证的第二渠道（例如既有发布审批记录）从发布负责人取得该次加密包的 **SHA-256 摘要**，作为 `-ExpectedSha256` 提供；它必须与传输包及同路旁车具有独立信任。不得读取下载目录旁车并直接作为安装信任值。旁车只用于传输诊断，不可代替签名或独立渠道；当前没有自动签名链，来源保障依赖运维核实发布身份与第二渠道。安装器持有同一只读文件句柄先校验，再解密；缺值、格式错误或不匹配均在读取包明文前失败。

安装端脚本及 `_lib.ps1` 也须来自可信代码渠道；不得先从待验便携包提取并执行启动程序。

## 3. 在全新目标机预检

- 预装经验证的 PostgreSQL 18（本机 `127.0.0.1:5432`）及可信 `psql`/`pg_restore`、nginx、Redis、NSSM、VC++ 运行库和 OpenSSL 3；本机必须带 Windows 系统 `tar.exe`、使用 Schannel 的 `curl.exe`。应用目标路径的父目录必须已存在、由管理员控制；`-TargetDir` 与 `-NginxDir` 不能含空格。目标盘至少有 8 GB 空闲，另需满足 `%ProgramData%` 暂存空间。
- 准备目标机的 PEM 叶证书加中间链、对应未加密 PEM 私钥（仅管理员可读），以及独立取得的单张 PEM 根证书。预先将该根证书部署到目标机 Windows 本机受信根与使用者客户端。`-ServerIP` 指 HTTPS 的固定 DNS 名/IP，必须匹配证书 SAN。安装器在任何部署变更前检查 Windows 根证书、链、时效、服务端用途、主机名和密钥匹配；不自动安装信任根，不降级到 HTTP。
- 按目标环境入站策略，由管理员在验收后开放 **443/TCP** 给业务客户端。脚本不添加防火墙放行规则。**3000 不提供业务**：仅对匹配 Host 跳转 HTTPS，未知 Host 拒绝；`/nginx-health` 与 `/metrics` 仅作环回探针。5002 / 6379 / 6380 也仅本机使用。

在目标机以管理员执行（替换参数中的占位值）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy\install_package.ps1 `
    -PreflightOnly -Package D:\incoming\erp_portable_release.tar.gz.enc `
    -ExpectedSha256 $TrustedReleaseHash -ServerIP erp.example.test `
    -TlsCertificate D:\tls\server-chain.pem -TlsPrivateKey D:\tls\server.key `
    -TlsTrustedCa D:\tls\root-ca.pem -OpenSsl 'C:\Program Files\OpenSSL\bin\openssl.exe'
```

`-TargetDir` 默认 `D:\erp_system`，`-NginxDir`、`-RedisDir`、`-Nssm` 默认分别为 `C:\nginx`、`C:\Redis`、`C:\nssm\nssm.exe`。预检只提示包口令，只读检查端口/服务冲突，在专用 ACL 内校验、解包并检查 TLS 配置，随后清理暂存。它不连接数据库、不创建目标目录、不启停服务，也不证明库可用。不要把预检通过当作安装成功。原有版本及其备份应原样保留。

## 验证范围

`powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy\tests\e2e_dryrun.ps1` 现只做语法解析、合成文件与辅助函数测试，不调用安装/构建脚本，不连库。真正放行前仍须在隔离 Windows VM 验证可信 TLS（含反例）、端口隔离、ACL/残留、物料完整性、五服务、新装失败恢复及可计时回切；**当前不应据这套自动化检查宣布生产迁机或原地升级可用**。
