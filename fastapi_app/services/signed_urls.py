"""OPT-19：/static/uploads/ 签名 URL 签发（与 nginx secure_link_md5 对齐）。

背景：/static/uploads/ 由 nginx alias 直接托管，知道 URL 即可 GET（免鉴权直出）。
文件名虽为 uuid4 不可枚举（storage_service.py:165），但被分享的链接永久有效。
本模块签发带过期时间的 secure_link_md5 摘要链接，nginx 侧 secure_link 校验后放行。

URL 形态（nginx secure_link_md5 标准协议）：
    /static/uploads/<key>?st=<到期Unix时间>&s=<base64url(md5(expired + uri + " " + secret))>

算法（与 nginx `secure_link_md5 "$secure_link_expires$uri <secret>"` 对齐）：
    md5(f"{expired}{uri} {secret}") 的 base64url（无填充）。
    注意 secret 前有一个**字面空格**（nginx 官方示例的写法），两侧必须严格一致：
    2026-10-01 实测无空格签名 403、带空格 200。
    注：MD5 是 nginx secure_link 协议的固定哈希（无法换成 SHA-256）；
    链接有效性由"密钥保密 + 短时效"保证，MD5 碰撞不构成攻击面
    （攻击者无密钥，无法对任意路径伪造摘要）。

密钥来源：UPLOAD_URL_SIGNING_SECRET 环境变量；为空时 sign_upload_url 返回
原 URL（签发禁用，nginx 侧相应不启用 secure_link）——配置联动 fail-safe。
"""
from __future__ import annotations

import base64
import hashlib
import os
import time
from urllib.parse import quote

from fastapi_app.core.logger import get_logger

logger = get_logger(__name__)


def signing_secret() -> str:
    """签名密钥；空串表示签名 URL 功能未启用。"""
    return os.getenv("UPLOAD_URL_SIGNING_SECRET", "").strip()


def sign_upload_url(key: str, ttl_seconds: int = 3600) -> str:
    """为 storage key 签发限时访问 URL（幂等：已带签名的 URL 原样返回）。

    Args:
        key: storage key 或完整路径（"/static/uploads/xxx" 或 "xxx.webp" 均可；
             含 query 的已签名 URL 原样返回，防止二次签名）。
        ttl_seconds: 链接有效期（默认 1 小时）。

    Returns:
        签名 URL（/static/uploads/<key>?st=..&s=..）；密钥未配置时返回原 URL。
    """
    # 幂等防重签：调用方可能传入已签名的 URL（如同一行数据被多个序列化层处理）
    if '?' in key:
        return key
    # 兼容传完整路径的调用方：剥掉前缀取 storage key
    prefix = '/static/uploads/'
    if key.startswith(prefix):
        key = key[len(prefix):]
    url = f"/static/uploads/{key}"
    secret = signing_secret()
    if not secret:
        return url

    expired = int(time.time()) + ttl_seconds
    # $uri 为 nginx 解码后的请求路径；签名与校验两侧都用完整路径保持一致。
    uri = quote(url, safe="/")
    # nginx secure_link_md5 的哈希输入 = 表达式求值后的整串。conf 写
    # `"$secure_link_expires$uri <secret>"` 时 <secret> 前有一个字面空格
    # （这是 nginx 官方示例的约定写法，两侧必须严格一致——2026-10-01 实测
    # 无空格签名 403、带空格 200）。md5 为 secure_link 协议固定哈希。
    raw = f"{expired}{uri} {secret}".encode()
    sig = base64.urlsafe_b64encode(hashlib.md5(raw).digest()).rstrip(b"=").decode("ascii")  # nosec B324 - nginx secure_link 协议固定哈希
    return f"{url}?st={expired}&s={sig}"


def verify_signature(key: str, expired: int, sig: str, secret: str | None = None) -> bool:
    """纯函数校验（供后端测试与对账使用；生产校验在 nginx secure_link 完成）。

    ⚠️ **不得用作鉴权判据**：签名功能未启用（UPLOAD_URL_SIGNING_SECRET 为空）时本函数
    返回 True —— 那是「签名未启用 ⇒ 不校验」，不是「校验通过」。需要鉴权请走
    require_permission 之类的依赖，不要把本函数当授权入口。
    """
    secret = secret or signing_secret()
    if not secret:
        logger.debug('签名未启用（UPLOAD_URL_SIGNING_SECRET 为空），verify_signature 不做校验')
        return True
    if expired < int(time.time()):
        return False
    uri = quote(f"/static/uploads/{key}", safe="/")
    raw = f"{expired}{uri} {secret}".encode()
    expect = base64.urlsafe_b64encode(hashlib.md5(raw).digest()).rstrip(b"=").decode("ascii")  # nosec B324 - 同上
    return sig == expect
