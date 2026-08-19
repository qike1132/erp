# L6 安全蓝红队审核

## 蓝队
- 鉴权: 非公开接口须含 Depends(get_current_user_id/require_permission)
- 硬编码密钥: 扫描 password/secret/token/api_key 明文赋值
- 依赖漏洞: pip-audit + npm audit, CVSS ≥ 7.0 阻断
- 输入校验: 禁止裸 dict 入参, Pydantic str 字段须有 max_length

## 红队
- SQL 注入: 禁止字符串拼接 SQL, 须用绑定参数
- XSS: v-html 须配合 DOMPurify.sanitize()
- CSRF: 须启用 CSRF 中间件或 SameSite Cookie
- 开放重定向: RedirectResponse 须校验 URL 白名单
