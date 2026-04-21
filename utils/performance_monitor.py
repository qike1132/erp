"""
性能监控模块
提供请求性能监控、慢查询日志、错误追踪功能 (FastAPI 兼容版本)
"""
import time
import functools
import logging
from datetime import datetime
import traceback
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class PerformanceMiddleware(BaseHTTPMiddleware):
    """FastAPI 性能监控中间件"""
    
    def __init__(self, app, slow_query_threshold: float = 1.0,
                 slow_request_threshold: float = 2.0):
        super().__init__(app)
        self.slow_query_threshold = slow_query_threshold
        self.slow_request_threshold = slow_request_threshold
        self.stats = {
            'total_requests': 0,
            'slow_requests': 0,
            'errors': 0,
            'avg_response_time': 0.0
        }
    
    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.time()
        request_id = request.headers.get('X-Request-ID', str(time.time()))
        
        try:
            response = await call_next(request)
            elapsed = time.time() - start_time
            
            response.headers['X-Response-Time'] = f"{elapsed:.3f}s"
            response.headers['X-Request-ID'] = request_id
            
            if elapsed > self.slow_request_threshold:
                self._log_slow_request(request, response, elapsed)
            
            self._update_stats(elapsed)
            
            return response
            
        except Exception as e:
            elapsed = time.time() - start_time
            self.stats['errors'] += 1
            logger.error(
                f"应用错误: {type(e).__name__} - {str(e)} - "
                f"路径: {request.url.path} - "
                f"方法: {request.method} - "
                f"IP: {request.client.host if request.client else 'unknown'}",
                exc_info=True
            )
            raise
    
    def _log_slow_request(self, request: Request, response: Response, elapsed: float):
        """记录慢请求"""
        logger.warning(
            f"慢请求: {request.method} {request.url.path} - "
            f"耗时: {elapsed:.3f}s - "
            f"状态码: {response.status_code} - "
            f"IP: {request.client.host if request.client else 'unknown'}"
        )
        self.stats['slow_requests'] += 1
    
    def _update_stats(self, elapsed: float):
        """更新性能统计"""
        self.stats['total_requests'] += 1
        
        total = self.stats['total_requests']
        current_avg = self.stats['avg_response_time']
        self.stats['avg_response_time'] = (
            (current_avg * (total - 1) + elapsed) / total
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


performance_monitor = PerformanceMiddleware.__new__(PerformanceMiddleware)


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
            
            if elapsed > 1.0:
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


query_tracker = QueryPerformanceTracker()


def track_db_query(f):
    """数据库查询追踪装饰器"""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        start_time = time.time()
        
        try:
            result = f(*args, **kwargs)
            elapsed = time.time() - start_time
            
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


cache_monitor = CachePerformanceMonitor()
