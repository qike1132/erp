"""
CDN配置模块
实现静态文件CDN支持
"""
from flask import url_for
import os


class CDNConfig:
    """CDN配置类"""
    
    def __init__(self, app=None):
        """
        初始化CDN配置
        
        Args:
            app: Flask应用实例
        """
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app):
        """初始化Flask应用"""
        self.app = app
        
        self.cdn_domain = app.config.get('CDN_DOMAIN', '')
        self.cdn_https = app.config.get('CDN_HTTPS', True)
        self.cdn_timestamp = app.config.get('CDN_TIMESTAMP', True)
        self.cdn_debug = app.config.get('CDN_DEBUG', False)
        
        if self.cdn_domain and not app.debug or self.cdn_debug:
            app.context_processor(self.inject_cdn_url)
    
    def inject_cdn_url(self):
        """注入CDN URL到模板上下文"""
        return {
            'cdn_url': self.cdn_url,
            'static_url': self.static_url
        }
    
    def cdn_url(self, endpoint, filename):
        """
        生成CDN URL
        
        Args:
            endpoint: 端点名称
            filename: 文件名
        
        Returns:
            CDN URL字符串
        """
        if not self.cdn_domain:
            return url_for(endpoint, filename=filename)
        
        if self.cdn_timestamp:
            static_folder = self.app.static_folder
            if static_folder:
                file_path = os.path.join(static_folder, filename)
                if os.path.exists(file_path):
                    timestamp = int(os.path.getmtime(file_path))
                    filename = f'{filename}?v={timestamp}'
        
        scheme = 'https' if self.cdn_https else 'http'
        return f'{scheme}://{self.cdn_domain}/{filename}'
    
    def static_url(self, filename):
        """
        生成静态文件URL
        
        Args:
            filename: 文件名
        
        Returns:
            静态文件URL
        """
        return self.cdn_url('static', filename)


def init_cdn(app):
    """
    初始化CDN配置
    
    Args:
        app: Flask应用实例
    """
    cdn = CDNConfig(app)
    
    return cdn


class CDNMiddleware:
    """CDN中间件"""
    
    def __init__(self, app, cdn_domain=None):
        """
        初始化CDN中间件
        
        Args:
            app: Flask应用实例
            cdn_domain: CDN域名
        """
        self.app = app
        self.cdn_domain = cdn_domain or app.config.get('CDN_DOMAIN', '')
    
    def __call__(self, environ, start_response):
        """处理请求"""
        if self.cdn_domain and self._is_static_request(environ):
            environ['HTTP_X_FORWARDED_PROTO'] = 'https'
        
        return self.app(environ, start_response)
    
    def _is_static_request(self, environ):
        """判断是否为静态文件请求"""
        path = environ.get('PATH_INFO', '')
        static_prefix = self.app.static_url_path or '/static'
        
        return path.startswith(static_prefix)
