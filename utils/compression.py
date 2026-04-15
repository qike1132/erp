"""
压缩中间件
实现HTTP响应压缩
"""
from flask import Flask, request, Response
from functools import wraps
import gzip
import io


class CompressionMiddleware:
    """压缩中间件类"""
    
    def __init__(self, app=None, minimum_size=500, compression_level=6):
        """
        初始化压缩中间件
        
        Args:
            app: Flask应用实例
            minimum_size: 最小压缩大小（字节）
            compression_level: 压缩级别（1-9）
        """
        self.minimum_size = minimum_size
        self.compression_level = compression_level
        
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app):
        """初始化Flask应用"""
        self.app = app
        app.after_request(self.compress_response)
    
    def compress_response(self, response):
        """压缩响应"""
        if not self._should_compress(response):
            return response
        
        accept_encoding = request.headers.get('Accept-Encoding', '')
        if 'gzip' not in accept_encoding.lower():
            return response
        
        if response.status_code < 200 or response.status_code >= 300:
            return response
        
        response.direct_passthrough = False
        
        if isinstance(response.response, (list, tuple)):
            content = b''.join(response.response)
        else:
            content = response.get_data()
        
        if len(content) < self.minimum_size:
            return response
        
        gzip_buffer = io.BytesIO()
        with gzip.GzipFile(
            mode='wb',
            fileobj=gzip_buffer,
            compresslevel=self.compression_level
        ) as gzip_file:
            gzip_file.write(content)
        
        response.set_data(gzip_buffer.getvalue())
        
        response.headers['Content-Encoding'] = 'gzip'
        response.headers['Content-Length'] = len(response.get_data())
        response.headers['Vary'] = 'Accept-Encoding'
        
        return response
    
    def _should_compress(self, response):
        """判断是否应该压缩"""
        if 'Content-Encoding' in response.headers:
            return False
        
        content_type = response.headers.get('Content-Type', '')
        compressible_types = [
            'text/html',
            'text/css',
            'text/javascript',
            'application/javascript',
            'application/json',
            'application/xml',
            'text/xml',
            'text/plain'
        ]
        
        return any(ct in content_type for ct in compressible_types)


def init_compression(app):
    """
    初始化压缩中间件
    
    Args:
        app: Flask应用实例
    """
    compression = CompressionMiddleware(
        app=app,
        minimum_size=app.config.get('COMPRESSION_MIN_SIZE', 500),
        compression_level=app.config.get('COMPRESSION_LEVEL', 6)
    )
    
    return compression
