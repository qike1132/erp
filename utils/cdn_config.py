"""
CDN配置模块
实现静态文件CDN支持 (FastAPI 兼容版本)
"""
import os
import time


class CDNConfig:
    """CDN配置类 (FastAPI 兼容)"""
    
    def __init__(self, cdn_domain: str = '', cdn_https: bool = True, 
                 cdn_timestamp: bool = True, static_folder: str = None):
        """
        初始化CDN配置
        
        Args:
            cdn_domain: CDN域名
            cdn_https: 是否使用HTTPS
            cdn_timestamp: 是否添加时间戳
            static_folder: 静态文件目录
        """
        self.cdn_domain = cdn_domain
        self.cdn_https = cdn_https
        self.cdn_timestamp = cdn_timestamp
        self.static_folder = static_folder or os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')
    
    def cdn_url(self, filename: str) -> str:
        """
        生成CDN URL
        
        Args:
            filename: 文件名
        
        Returns:
            CDN URL字符串
        """
        if not self.cdn_domain:
            return f'/static/{filename}'
        
        if self.cdn_timestamp:
            file_path = os.path.join(self.static_folder, filename)
            if os.path.exists(file_path):
                timestamp = int(os.path.getmtime(file_path))
                filename = f'{filename}?v={timestamp}'
        
        scheme = 'https' if self.cdn_https else 'http'
        return f'{scheme}://{self.cdn_domain}/{filename}'
    
    def static_url(self, filename: str) -> str:
        """
        生成静态文件URL
        
        Args:
            filename: 文件名
        
        Returns:
            静态文件URL
        """
        return self.cdn_url(filename)