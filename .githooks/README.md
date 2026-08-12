# Git Hooks — UTF-8 提交规范

防止 GBK 编码终端产生的乱码提交信息（历史中如 "淇敼" 实为 GBK 编码的"修改"）再次入库。

## Hook 说明

| Hook | 作用 |
|---|---|
| `commit-msg` | 校验提交信息是合法 UTF-8 且不含乱码替换字符 U+FFFD，否则拒绝提交 |

## 启用方式（每个 clone / 新环境执行一次）

```bash
git config core.hooksPath .githooks
git config i18n.commitEncoding utf-8
git config i18n.logOutputEncoding utf-8
git config core.quotepath false
```

- `core.hooksPath`：启用本目录的 hook
- `i18n.commitEncoding`：声明提交信息为 UTF-8
- `i18n.logOutputEncoding`：`git log` 以 UTF-8 输出
- `core.quotepath false`：`git status` / `git log` 正常显示中文文件名（不转义）

## 与 Husky 的关系

仓库根的 `.husky/`（frontend-vite 的 husky 配置，含 pre-commit lint-staged）
当前**未激活**（`core.hooksPath` 未指向 `.husky/_`）。若之后在 frontend-vite 执行
`npm install` 激活了 husky，它会重置 `core.hooksPath`，届时请将本 hook 并入 husky：

```bash
cd frontend-vite
npx husky add .husky/commit-msg "bash ../.githooks/commit-msg"
```

## 测试

```bash
# 合法 UTF-8 → 通过 (exit 0)
printf '测试提交\n' > /tmp/msg-ok.txt && bash .githooks/commit-msg /tmp/msg-ok.txt; echo $?

# GBK 编码 → 拒绝 (exit 1)
python -c "open('/tmp/msg-gbk.txt','wb').write('测试提交'.encode('gbk'))" && bash .githooks/commit-msg /tmp/msg-gbk.txt; echo $?

# 含 U+FFFD 替换字符 → 拒绝 (exit 1)
printf '\xef\xbf\xbd乱码\n' > /tmp/msg-fffd.txt && bash .githooks/commit-msg /tmp/msg-fffd.txt; echo $?
```
