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


_UPLOAD_PREFIX = '/static/uploads/'

# 签发到期时间的对齐桶（秒）。st 从"now+ttl"改为"向上对齐到桶边界"，同一张图在
# 桶内的所有签发得到**逐字节相同**的 URL —— 浏览器磁盘缓存（nginx 侧已发
# expires 7d immutable）跨翻页/跨会话命中，不再每页全量重下（2026-10-09 用户
# 报告：翻页后图片延迟 1-2s）。桶化只让实际有效期在 ttl ~ ttl+BUCKET 之间浮动，
# nginx secure_link 判定与 md5 公式零改动。
SIGN_EXPIRY_BUCKET_SECONDS = 3600


def _url_path(u: str) -> str:
    """取 URL 的 path 部分（剥掉 `scheme://host` 与 query）。

    用于识别**自站的绝对 URL**（用户从地址栏整串粘贴的 `https://host:3000/static/uploads/…`）
    —— 这类也是本地上传件，签名要剥、且**必须还原成相对 path**：
    出站 `sign_image_url` 对带 scheme/netloc 的值**原样返回不重签**，
    若把绝对 URL 落库，nginx secure_link 会**立即 403**（比"过期后 410"更糟）。
    """
    bare = u.split('?', 1)[0]
    low = bare.lower()  # scheme 大小写不敏感（HTTP:// 也要认）
    if low.startswith(('http://', 'https://')):
        rest = bare.split('://', 1)[1]
    elif bare.startswith('//'):
        rest = bare[2:]
    else:
        return bare
    slash = rest.find('/')
    return rest[slash:] if slash != -1 else '/'


def strip_upload_signature(url: str) -> str:
    """剥掉**本地上传**引用上的签名 query，得到可长期入库的**相对路径**。

    上传接口返回的是**限时签名** URL（`/static/uploads/x.webp?st=..&s=..`）。
    若把带签名的整串**原样存库**，读时 `sign_upload_url` 会因"已含 ?"而按幂等
    分支**原样返回**（不再重新签发）→ 过了 `st` 的到期时间，nginx secure_link
    返回 **410**，图片/附件永久失效且无法自愈。
    2026-10-02 P4/P5 审计实测据此确认：产品新增/编辑（哪怕只改名）约 1 小时后
    图片 410。落库只存 key/路径，签名一律在出站时现签。

    ⚠️ 只对**本地**上传路径动手：`schemas/product.py` 明确放行外部 http(s) 直链，
    那些 URL 的 query（如 CDN 的 `?token=…`）是对方签发的，剥掉会让外链失效。
    判定按 **path**；**自站绝对 URL 也要还原成相对 path**（否则出站不重签 → 403）。
    """
    if not url:
        return url
    path = _url_path(url)
    if path.startswith(_UPLOAD_PREFIX):
        return path
    # 兼容裸 storage key（无前缀）形态：仅当带的是本系统的签名参数时才剥
    if not url.startswith(('http://', 'https://', '//')) and '?st=' in url and '&s=' in url:
        return path
    return url


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

    # 到期时间对齐到桶边界：桶内重复签发 URL 相同 → 浏览器缓存命中。
    # 不变量：对齐后 st ∈ [now+ttl, now+ttl+bucket)（有效期永不缩水）。
    now = int(time.time())
    expired = now + ttl_seconds
    bucket = SIGN_EXPIRY_BUCKET_SECONDS
    aligned = expired - (expired % bucket)
    if aligned < expired:
        aligned += bucket  # 向下取整丢了一段窗口 → 跳到下一桶边界
    expired = aligned
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
