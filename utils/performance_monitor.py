"""
性能监控模块
提供请求性能监控、慢查询日志、错误追踪功能
"""
import time
import functools
import logging
from flask import request, g, jsonify
from datetime import datetime
import traceback

logger = logging.getLogger(__name__)


class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self, app=None):
        self.app = app
        self.slow_query_threshold = 1.0  # 慢查询阈值(秒)
        self.slow_request_threshold = 2.0  # 慢请求阈值(秒)
        self.stats = {
            'total_requests': 0,
            'slow_requests': 0,
            'errors': 0,
            'avg_response_time': 0.0
        }
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """初始化性能监控"""
        self.app = app
        
        # 从配置读取阈值
        self.slow_query_threshold = app.config.get('SLOW_QUERY_THRESHOLD', 1.0)
        self.slow_request_threshold = app.config.get('SLOW_REQUEST_THRESHOLD', 2.0)
        
        # 注册请求钩子
        @app.before_request
        def before_request():
            g.start_time = time.time()
            g.request_id = request.headers.get('X-Request-ID', str(time.time()))
        
        @app.after_request
        def after_request(response):
            if hasattr(g, 'start_time'):
                elapsed = time.time() - g.start_time
                
                # 记录慢请求
                if elapsed > self.slow_request_threshold:
                    self._log_slow_request(request, response, elapsed)
                
                # 更新统计
                self._update_stats(elapsed)
                
                # 添加性能头
                response.headers['X-Response-Time'] = f"{elapsed:.3f}s"
                response.headers['X-Request-ID'] = getattr(g, 'request_id', 'unknown')
            
            return response
        
        # 注册错误处理器
        @app.errorhandler(Exception)
        def handle_exception(e):
            self._track_error(e)
            raise e
    
    def _log_slow_request(self, request, response, elapsed):
        """记录慢请求"""
        logger.warning(
            f"慢请求: {request.method} {request.path} - "
            f"耗时: {elapsed:.3f}s - "
            f"状态码: {response.status_code} - "
            f"IP: {request.remote_addr}"
        )
        
        self.stats['slow_requests'] += 1
    
    def _update_stats(self, elapsed):
        """更新性能统计"""
        self.stats['total_requests'] += 1
        
        # 计算平均响应时间
        total = self.stats['total_requests']
        current_avg = self.stats['avg_response_time']
        self.stats['avg_response_time'] = (
            (current_avg * (total - 1) + elapsed) / total
        )
    
    def _track_error(self, error):
        """追踪错误"""
        self.stats['errors'] += 1
        
        logger.error(
            f"应用错误: {type(error).__name__} - {str(error)} - "
            f"路径: {request.path} - "
            f"方法: {request.method} - "
            f"IP: {request.remote_addr}",
            exc_info=True
        )
    
    def get_stats(self):
        """获取性能统计"""
        return {
            **self.stats,
            'slow_query_threshold': self.slow_query_threshold,
            'slow_request_threshold': self.slow_request_threshold,
            'timestamp': datetime.now().isoformat()
        }
    
    def reset_stats(self):
        """重置统计"""
        self.stats = {
            'total_requests': 0,
            'slow_requests': 0,
            'errors': 0,
            'avg_response_time': 0.0
        }


# 全局性能监控实例
performance_monitor = PerformanceMonitor()


def monitor_performance(f):
    """
    性能监控装饰器
    用于监控特定函数的执行时间
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        start_time = time.time()
        
        try:
            result = f(*args, **kwargs)
            elapsed = time.time() - start_time
            
            # 记录执行时间
            if elapsed > performance_monitor.slow_query_threshold:
                logger.warning(
                    f"慢函数执行: {f.__name__} - 耗时: {elapsed:.3f}s"
                )
            
            return result
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"函数执行错误: {f.__name__} - 耗时: {elapsed:.3f}s - "
                f"错误: {str(e)}",
                exc_info=True
            )
            raise
    
    return decorated_function


class QueryPerformanceTracker:
    """数据库查询性能追踪器"""
    
    def __init__(self):
        self.queries = []
        self.slow_queries = []
        self.threshold = 1.0
    
    def track_query(self, query, params=None, elapsed=None):
        """追踪查询"""
        query_info = {
            'query': str(query),
            'params': str(params) if params else None,
            'elapsed': elapsed,
            'timestamp': datetime.now().isoformat()
        }
        
        self.queries.append(query_info)
        
        # 记录慢查询
        if elapsed and elapsed > self.threshold:
            self.slow_queries.append(query_info)
            logger.warning(
                f"慢查询: {query} - 耗时: {elapsed:.3f}s - "
                f"参数: {params}"
            )
    
    def get_slow_queries(self):
        """获取慢查询列表"""
        return self.slow_queries
    
    def get_stats(self):
        """获取查询统计"""
        return {
            'total_queries': len(self.queries),
            'slow_queries': len(self.slow_queries),
            'avg_time': sum(q['elapsed'] for q in self.queries if q['elapsed']) / len(self.queries) if self.queries else 0
        }
    
    def clear(self):
        """清空记录"""
        self.queries.clear()
        self.slow_queries.clear()


# 全局查询追踪器
query_tracker = QueryPerformanceTracker()


def track_db_query(f):
    """
    数据库查询追踪装饰器
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        start_time = time.time()
        
        try:
            result = f(*args, **kwargs)
            elapsed = time.time() - start_time
            
            # 追踪查询
            query_tracker.track_query(
                query=f.__name__,
                params={'args': args, 'kwargs': kwargs},
                elapsed=elapsed
            )
            
            return result
            
        except Exception as e:
            elapsed = time.time() - start_time
            query_tracker.track_query(
                query=f.__name__,
                params={'args': args, 'kwargs': kwargs},
                elapsed=elapsed
            )
            raise
    
    return decorated_function


class CachePerformanceMonitor:
    """缓存性能监控"""
    
    def __init__(self):
        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'deletes': 0
        }
    
    def record_hit(self):
        """记录缓存命中"""
        self.stats['hits'] += 1
    
    def record_miss(self):
        """记录缓存未命中"""
        self.stats['misses'] += 1
    
    def record_set(self):
        """记录缓存设置"""
        self.stats['sets'] += 1
    
    def record_delete(self):
        """记录缓存删除"""
        self.stats['deletes'] += 1
    
    def get_hit_rate(self):
        """获取缓存命中率"""
        total = self.stats['hits'] + self.stats['misses']
        return (self.stats['hits'] / total * 100) if total > 0 else 0
    
    def get_stats(self):
        """获取缓存统计"""
        return {
            **self.stats,
            'hit_rate': f"{self.get_hit_rate():.2f}%",
            'total_requests': self.stats['hits'] + self.stats['misses']
        }
    
    def reset(self):
        """重置统计"""
        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'deletes': 0
        }


# 全局缓存监控实例
cache_monitor = CachePerformanceMonitor()


if __name__ == '__main__':
    print("性能监控模块")
    print("\n功能:")
    print("1. 请求性能监控")
    print("2. 慢查询日志")
    print("3. 错误追踪")
    print("4. 缓存性能监控")
