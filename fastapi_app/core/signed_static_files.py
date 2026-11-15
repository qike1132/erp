"""uploads 静态目录的应用层签名校验（纵深防御）。

现状与缺口
----------
`/static/uploads` 由 nginx `alias` 直接托管，nginx 侧已有 `secure_link` 校验
（config/nginx-windows.conf 的 secure_link/secure_link_md5，链接由
`fastapi_app.services.signed_urls.sign_upload_url` 签发）。但**应用层此前零防护**：
`main.py` 把 uploads 挂成无依赖的 `StaticFiles`，任何绕过 nginx 的路径
（直连 uvicorn 端口、其它反代、内网调试、容器内探测）都能免签名取走文件。

本模块把同一套判据补到应用层，结果码与 nginx `secure_link` 语义对齐：

| 情况                                  | nginx                     | 本模块 |
|---------------------------------------|---------------------------|--------|
| 签名缺失 / 摘要不匹配                  | 403（$secure_link 为空）   | 403    |
| 摘要匹配但已过期                       | 410（$secure_link == "0"） | 410    |
| 摘要匹配且未过期                       | 200                        | 200    |
| 密钥未配置（签名功能未启用，开发环境）  | 不启用 secure_link → 200   | 200    |

「密钥未配置 ⇒ 不校验」这条**必须**在调用 `verify_signature` 之前判掉：该函数
未启用时返回 True（「未启用 ⇒ 不校验」≠「校验通过」），直接拿它当鉴权入口会把
开发环境的口径误用到生产。
"""
from __future__ import annotations

import time

from starlette.datastructures import QueryParams
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from fastapi_app.services.signed_urls import signature_matches, signing_secret, verify_signature

# 与 nginx secure_link 的结果码对齐
_STATUS_MISSING_OR_INVALID = 403
_STATUS_EXPIRED = 410


class SignedUploadsStaticFiles(StaticFiles):
    """`/static/uploads` 专用 StaticFiles：出响应前校验 `?st=&s=` 签名。

    只加一道**前置校验**，其余行为（Range/304/404/405、目录穿越防护）全部沿用
    `StaticFiles.get_response` —— 故 Range 请求、浏览器磁盘缓存（ETag/
    Last-Modified）语义与改造前完全一致。

    挂载参数与普通 StaticFiles 相同：`app.mount("/static/uploads",
    SignedUploadsStaticFiles(directory=...), name="static-uploads")`。
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        _assert_upload_signature(path, scope)
        return await super().get_response(path, scope)


def _assert_upload_signature(path: str, scope: Scope) -> None:
    """校验 uploads 访问签名；不通过抛 403/410，通过静默返回。

    Args:
        path: `StaticFiles.get_path(scope)` 得到的相对路径（未加 `/static/uploads/` 前缀）。
        scope: ASGI scope，只用到 `query_string`。

    Raises:
        HTTPException: 403（签名缺失/不匹配）、410（签名匹配但已过期）。
    """
    secret = signing_secret()
    if not secret:
        # 签名功能未启用（开发/未配置）——保持改造前行为放行。
        return

    # Windows 下 StaticFiles.get_path 用 os.path.normpath，分隔符会变成 `\`，
    # 而签名是对 nginx 的 `/static/uploads/<key>` 路径算的，必须先归一成 `/`。
    key = path.replace("\\", "/")

    params = QueryParams(scope.get("query_string", b""))
    sig, expires = params.get("s"), params.get("st")
    if not sig or not expires:
        raise HTTPException(status_code=_STATUS_MISSING_OR_INVALID)
    try:
        expires_at = int(expires)
    except ValueError as exc:
        raise HTTPException(status_code=_STATUS_MISSING_OR_INVALID) from exc

    if verify_signature(key, expires_at, sig, secret):
        return
    # verify_signature 把「已过期」也归为不通过；这里再用只看摘要的
    # signature_matches 区分失败原因，才能给出与 nginx 一致的 410。
    if signature_matches(key, expires_at, sig, secret) and expires_at < int(time.time()):
        raise HTTPException(status_code=_STATUS_EXPIRED)
    raise HTTPException(status_code=_STATUS_MISSING_OR_INVALID)
