"""
压缩中间件
实现HTTP响应压缩 (Starlette/FastAPI 兼容版本)
"""
import gzip


class CompressionMiddleware:
    """Starlette/FastAPI 压缩中间件类"""

    def __init__(self, minimum_size=500, compression_level=6):
        """
        初始化压缩中间件

        Args:
            minimum_size: 最小压缩大小（字节）
            compression_level: 压缩级别（1-9）
        """
        self.minimum_size = minimum_size
        self.compression_level = compression_level

    async def __call__(self, scope, receive, send):
        """ASGI 中间件入口"""
        if scope["type"] != "http":
            return await send(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                content_type = headers.get(b"content-type", b"").decode()
                if not self._should_compress_type(content_type):
                    await send(message)
                    return

            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if len(body) < self.minimum_size:
                    await send(message)
                    return

                compressed = gzip.compress(body, compresslevel=self.compression_level)
                message["body"] = compressed
                message.setdefault("headers", []).extend([
                    (b"content-encoding", b"gzip"),
                ])

            await send(message)

        await send(scope, receive, send_wrapper)

    def _should_compress_type(self, content_type: str) -> bool:
        """判断内容类型是否可压缩"""
        compressible_types = [
            'text/html', 'text/css', 'text/javascript',
            'application/javascript', 'application/json',
            'application/xml', 'text/xml', 'text/plain'
        ]
        return any(ct in content_type for ct in compressible_types)


def init_compression(app):
    """
    初始化压缩中间件

    Args:
        app: FastAPI 应用实例
    """
    compression = CompressionMiddleware(
        app=app,
        minimum_size=app.config.get('COMPRESSION_MIN_SIZE', 500),
        compression_level=app.config.get('COMPRESSION_LEVEL', 6)
    )

    return compression
