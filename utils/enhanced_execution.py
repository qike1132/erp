"""
工具执行效率与架构增强模块 (借鉴 Claude CLI 多项核心设计)

包含:
  1. SpeculativeExecutor - 投机式预检执行器
  2. ResultCache - 工具结果缓存 (带依赖追踪)
  3. ParallelExecutor - 并行执行调度器
  4. ResilientRetry - 弹性重试机制 (指数退避+jitter)
  5. ErrorDiagnoser - 错误诊断系统 (cause chain遍历)
  6. CostTracker - 成本追踪器 (Token/API调用统计)
  7. SkillHotReloader - 技能热加载器
"""
import asyncio
import functools
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class SpeculativeResult:
    """投机执行结果"""
    ready: bool
    result: Any = None
    error: Exception | None = None
    elapsed_ms: float = 0
    source: str = 'speculative'


class SpeculativeExecutor:
    """
    投机式预检执行器 (借鉴 Claude CLI 的 Speculative Execution)

    在主流程等待用户确认时，后台预执行轻量级安全检查。
    高置信度结果直接使用，超时则走正常流程。

    典型场景:
        用户看到权限弹窗 → 后台启动分类检查(2s超时)
        → 高置信度匹配 → 静默批准
        → 超时/低置信度 → 显示弹窗让用户确认
    """

    def __init__(self, default_timeout_ms: float = 2000,
                 max_concurrent: int = 10):
        self.default_timeout_ms = default_timeout_ms
        self.max_concurrent = max_concurrent
        self._pending: dict[str, asyncio.Task] = {}
        self._results: dict[str, SpeculativeResult] = {}
        self._lock = threading.Lock()
        self.stats = {
            'speculations': 0,
            'hits': 0,
            'misses': 0,
            'timeouts': 0,
            'errors': 0
        }

    async def speculate(self, key: str, checker: Callable,
                        timeout_ms: float | None = None) -> SpeculativeResult:
        """
        发起投机执行

        Args:
            key: 唯一标识符
            checker: 异步检查函数
            timeout_ms: 超时时间(ms)
        """
        timeout = timeout_ms or self.default_timeout_ms
        self.stats['speculations'] += 1

        with self._lock:
            existing = self._results.get(key)
            if existing and existing.ready:
                self.stats['hits'] += 1
                return existing

        try:
            start_time = time.time()
            if asyncio.iscoroutinefunction(checker):
                result = await asyncio.wait_for(
                    asyncio.create_task(checker()),
                    timeout=timeout / 1000
                )
            else:
                loop = asyncio.get_running_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, checker),
                    timeout=timeout / 1000
                )
            elapsed = (time.time() - start_time) * 1000
            spec_result = SpeculativeResult(
                ready=True, result=result, elapsed_ms=elapsed,
                source='speculative_hit'
            )
            with self._lock:
                self._results[key] = spec_result
            return spec_result

        except TimeoutError:
            self.stats['timeouts'] += 1
            return SpeculativeResult(
                ready=False, elapsed_ms=timeout,
                source='timeout'
            )

        except Exception as e:
            self.stats['errors'] += 1
            return SpeculativeResult(
                ready=False, error=e,
                elapsed_ms=(time.time() - start_time) * 1000 if 'start_time' in dir() else 0,
                source='error'
            )

    def race(self, key: str, spec_task: Callable,
             fallback_timeout_ms: float = 2000) -> SpeculativeResult:
        """
        竞争模式 (借鉴 Claude CLI 的 Promise.race)

        同时启动投机任务和超时定时器，先到者胜出。
        """
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(spec_task)
            try:
                result = future.result(timeout=fallback_timeout_ms / 1000)
                self.stats['hits'] += 1
                return SpeculativeResult(ready=True, result=result, source='race_win')
            except concurrent.futures.TimeoutError:
                self.stats['misses'] += 1
                return SpeculativeResult(ready=False, elapsed_ms=fallback_timeout_ms, source='race_timeout')

    def invalidate(self, key: str):
        """使投机结果失效"""
        with self._lock:
            self._results.pop(key, None)

    def clear_all(self):
        """清空所有投机缓存"""
        with self._lock:
            self._results.clear()

    def get_stats(self) -> dict:
        return {**self.stats, 'cached_results': len(self._results)}


speculative_executor = SpeculativeExecutor()


class ResultCache:
    """
    工具结果缓存 (借鉴 Claude CLI 的结果复用机制)

    对相同输入的工具调用返回缓存结果，支持依赖失效。
    """

    def __init__(self, max_size: int = 200, default_ttl: float = 60.0):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, tuple[Any, float, float]] = OrderedDict()
        self._dependencies: dict[str, set] = {}
        self._tool_keys: dict[str, set] = {}
        self._lock = threading.RLock()
        self.stats = {'hits': 0, 'misses': 0, 'sets': 0, 'invalidations': 0}

    def _make_key(self, tool_name: str, input_data: Any) -> str:
        raw = f"{tool_name}:{json.dumps(input_data, sort_keys=True, default=str)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:20]

    def get(self, tool_name: str, input_data: Any) -> Any | None:
        cache_key = self._make_key(tool_name, input_data)
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry is None:
                self.stats['misses'] += 1
                return None
            value, expires_at, created_at = entry
            if time.time() > expires_at:
                del self._cache[cache_key]
                self.stats['misses'] += 1
                return None
            self._cache.move_to_end(cache_key)
            self.stats['hits'] += 1
            return value

    def set(self, tool_name: str, input_data: Any, result: Any,
            ttl: float | None = None, depends_on: list[str] | None = None):
        cache_key = self._make_key(tool_name, input_data)
        effective_ttl = ttl or self.default_ttl
        with self._lock:
            if len(self._cache) >= self.max_size:
                old_key, _ = self._cache.popitem(last=False)
                for tk in list(self._tool_keys.values()):
                    tk.discard(old_key)
            self._cache[cache_key] = (result, time.time() + effective_ttl, time.time())
            if tool_name not in self._tool_keys:
                self._tool_keys[tool_name] = set()
            self._tool_keys[tool_name].add(cache_key)
            if depends_on:
                for dep_key in depends_on:
                    if dep_key not in self._dependencies:
                        self._dependencies[dep_key] = set()
                    self._dependencies[dep_key].add(cache_key)
            self.stats['sets'] += 1

    def invalidate_by_tool(self, tool_name: str):
        """使某工具的所有缓存失效（数据变更后调用）"""
        with self._lock:
            keys_to_remove = self._tool_keys.pop(tool_name, set()).copy()
            for k in keys_to_remove:
                self._cache.pop(k, None)
                for dep_set in self._dependencies.values():
                    dep_set.discard(k)
            self.stats['invalidations'] += len(keys_to_remove)

    def invalidate_dependencies(self, resource_key: str):
        """使依赖于某资源的所有缓存失效"""
        with self._lock:
            dependent_keys = self._dependencies.pop(resource_key, set())
            for key in dependent_keys:
                self._cache.pop(key, None)
            self.stats['invalidations'] += len(dependent_keys)

    def get_stats(self) -> dict:
        total = self.stats['hits'] + self.stats['misses']
        return {
            **self.stats,
            'size': len(self._cache),
            'hit_rate': f"{self.stats['hits']/total*100:.1f}%" if total > 0 else "N/A"
        }


result_cache = ResultCache()


class ParallelExecutor:
    """
    并行执行调度器 (借鉴 Claude CLI 的并行工具调用)

    对无依赖关系的操作并行发起，汇总结果。
    支持最大并发数控制、错误隔离、进度回调。
    """

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.stats = {
            'total_tasks': 0,
            'parallel_executions': 0,
            'sequential_fallbacks': 0,
            'errors': 0
        }

    async def execute_parallel(self, tasks: list[tuple[str, Callable, tuple]],
                                progress_callback: Callable | None=None) -> list[tuple[str, Any]]:
        """
        并行执行多个任务

        Args:
            tasks: [(name, func, args), ...]
            progress_callback: (completed, total) -> None
        Returns:
            [(name, result), ...]
        """
        import asyncio
        self.stats['total_tasks'] += len(tasks)
        semaphore = asyncio.Semaphore(self.max_workers)
        results = []
        completed = [0]
        errors = []

        async def run_task(name, func, args):
            async with semaphore:
                try:
                    if asyncio.iscoroutinefunction(func):
                        result = await func(*args)
                    else:
                        loop = asyncio.get_running_loop()
                        result = await loop.run_in_executor(None, lambda: func(*args))
                    completed[0] += 1
                    if progress_callback:
                        progress_callback(completed[0], len(tasks))
                    return name, result
                except Exception as e:
                    completed[0] += 1
                    self.stats['errors'] += 1
                    errors.append((name, str(e)))
                    if progress_callback:
                        progress_callback(completed[0], len(tasks))
                    return name, e

        tasks_async = [run_task(name, func, args) for name, func, args in tasks]
        results = await asyncio.gather(*tasks_async, return_exceptions=True)
        self.stats['parallel_executions'] += 1
        return results

    def execute_sync_parallel(self, tasks: list[tuple[str, Callable, tuple]]) -> list[tuple[str, Any]]:
        """同步版本的并行执行（使用线程池）"""
        import concurrent.futures
        self.stats['total_tasks'] += len(tasks)
        results = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_map = {}
            for name, func, args in tasks:
                future = executor.submit(func, *args)
                future_map[future] = name

            for future in concurrent.futures.as_completed(future_map):
                name = future_map[future]
                try:
                    result = future.result()
                    results.append((name, result))
                except Exception as e:
                    self.stats['errors'] += 1
                    results.append((name, e))

        self.stats['parallel_executions'] += 1
        return results


parallel_executor = ParallelExecutor(max_workers=4)


class RetryConfig:
    """重试配置"""

    def __init__(self, max_retries: int = 10, base_delay_ms: float = 500,
                 max_delay_ms: float = 8000, jitter_range_ms: float = 1000,
                 permanent_errors: frozenset = frozenset({401, 403, 404})):
        self.max_retries = max_retries
        self.base_delay_ms = base_delay_ms
        self.max_delay_ms = max_delay_ms
        self.jitter_range_ms = jitter_range_ms
        self.permanent_errors = permanent_errors


DEFAULT_RETRY_CONFIG = RetryConfig()


def resilient_retry(config: RetryConfig | None = None,
                   on_retry: Callable[[int, Exception], None] | None = None):
    """
    弹性重试装饰器 (借鉴 Claude CLI 的指数退避+随机抖动)

    特性:
    - 指数退避: delay = base * 2^attempt
    - 随机抖动: 防止惊群效应
    - 永久性错误立即放弃: 4xx client error
    - 可重试错误自动重试: 5xx / network error

    用法:
        @resilient_retry(RetryConfig(max_retries=5))
        def api_call():
            ...
    """
    config = config or DEFAULT_RETRY_CONFIG
    import random

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    status_code = getattr(e, 'code', None) or getattr(e, 'status_code', None)

                    if status_code in config.permanent_errors:
                        raise

                    is_network_error = isinstance(e, (
                        ConnectionError, TimeoutError, OSError
                    ))
                    is_server_error = status_code and status_code >= 500

                    if not (is_network_error or is_server_error) and attempt > 0:
                        raise

                    if attempt < config.max_retries:
                        delay = min(
                            config.base_delay_ms * (2 ** attempt),
                            config.max_delay_ms
                        ) / 1000
                        jitter = random.uniform(0, config.jitter_range_ms) / 1000
                        if on_retry:
                            on_retry(attempt + 1, e)
                        time.sleep(delay + jitter)

            raise last_exception
        return wrapper
    return decorator


class ErrorDiagnoser:
    """
    错误诊断系统 (借鉴 Claude CLI 的19种SSL错误码映射 + cause chain遍历)

    提取根因、给出具体修复建议。
    """

    SSL_ERROR_CODES = {
        'UNABLE_TO_VERIFY_LEAF_SIGNATURE': '证书验证失败',
        'UNABLE_TO_GET_ISSUER_CERT': '无法获取颁发者证书',
        'CERT_SIGNATURE_FAILURE': '证书签名无效',
        'CERT_NOT_YET_VALID': '证书尚未生效',
        'CERT_HAS_EXPIRED': '证书已过期',
        'CERT_REVOKED': '证书已被吊销',
        'DEPTH_ZERO_SELF_SIGNED_CERT': '自签名证书',
        'SELF_SIGNED_CERT_IN_CHAIN': '证书链中存在自签名',
        'ERR_TLS_CERT_ALTNAME_INVALID': '证书域名不匹配',
        'HOSTNAME_MISMATCH': '主机名不匹配',
        'ERR_TLS_HANDSHAKE_TIMEOUT': 'TLS握手超时',
        'ERR_SSL_WRONG_VERSION_NUMBER': 'SSL版本号错误',
        'UNABLE_TO_GET_ISSUER_CERT_LOCALLY': '本地无法获取颁发者证书',
        'SSLV3_ALERT_HANDSHAKE_FAILURE': 'SSLv3握手失败',
        'ECONNREFUSED': '连接被拒绝',
        'ECONNRESET': '连接被重置',
        'ETIMEDOUT': '连接超时',
        'ENOTFOUND': 'DNS解析失败',
        'EACCES': '权限被拒绝'
    }

    NETWORK_FIXES = {
        'ECONNREFUSED': '目标服务未启动或端口被防火墙阻止。请检查服务状态和防火墙规则。',
        'ECONNRESET': '连接被远程主机强制关闭。可能是网络不稳定或服务端过载。',
        'ETIMEDOUT': '网络请求超时。请检查网络连接和服务端响应时间。',
        'ENOTFOUND': 'DNS解析失败。请检查域名是否正确和DNS服务器配置。',
        'EACCES': '权限被拒绝。请检查文件权限或以管理员身份运行。',
        'certificate_error': 'SSL/TLS证书问题。企业环境请设置NODE_EXTRA_CA_CERTS或联系IT部门将*.anthropic.com加入白名单。'
    }

    MAX_CAUSE_DEPTH = 5

    def diagnose(self, error: Exception) -> dict:
        """
        完整诊断错误

        返回: {
            'root_cause': 根因异常,
            'code': 错误码,
            'category': 分类,
            'message': 用户友好的错误描述,
            'fix_suggestion': 修复建议,
            'cause_chain': 原因链
        }
        """
        cause_chain = []
        current: Any = error
        depth = 0

        while current and depth < self.MAX_CAUSE_DEPTH:
            cause_chain.append({
                'type': type(current).__name__,
                'message': str(current),
                'code': getattr(current, 'code', None),
                'errno': getattr(current, 'errno', None)
            })
            if hasattr(current, 'cause') and current.cause != current:
                current = current.cause
                depth += 1
            else:
                break

        root_cause = cause_chain[-1] if cause_chain else error
        root_code = root_cause.get('code') or root_cause.get('errno')
        category = self._categorize(root_code, error)
        message = self._build_message(root_code, category, error)
        fix = self.NETWORK_FIXES.get(category, self.NETWORK_FIXES.get(str(root_code), '未知错误，请联系技术支持'))

        return {
            'root_cause': root_cause,
            'code': root_code,
            'category': category,
            'message': message,
            'fix_suggestion': fix,
            'cause_chain': cause_chain,
            'diagnosed_at': datetime.now().isoformat()
        }

    def _categorize(self, code: Any, error: Exception) -> str:
        if code in self.SSL_ERROR_CODES:
            return 'certificate_error'
        if isinstance(error, (ConnectionRefusedError, ConnectionResetError)):
            return 'connection_refused'
        if isinstance(error, TimeoutError):
            return 'timeout'
        if isinstance(error, FileNotFoundError):
            return 'file_not_found'
        if isinstance(error, PermissionError):
            return 'permission_denied'
        if isinstance(error, (ValueError, TypeError)):
            return 'validation_error'
        return 'unknown'

    def _build_message(self, code: Any, category: str, error: Exception) -> str:
        ssl_desc = self.SSL_ERROR_CODES.get(code, '')
        if ssl_desc:
            return f"SSL/TLS证书错误 ({ssl_desc})。如果使用了代理或防火墙，可能需要配置CA证书。"
        base_msg = f"{type(error).__name__}: {str(error)}"
        if category == 'certificate_error':
            return base_msg + " 企业代理环境下请配置正确的CA证书。"
        return base_msg


error_diagnoser = ErrorDiagnoser()


class CostTracker:
    """
    成本追踪器 (借鉴 Claude CLI 的 cost-tracker)

    追踪API调用的Token消耗和估算成本。
    """

    def __init__(self):
        self._session_costs: list[dict] = []
        self._current_session: dict | None = None
        self._lock = threading.Lock()

        self.pricing = {
            'input_token_cost': 0.000003,
            'output_token_cost': 0.000015,
            'cache_read_cost': 0.0000003,
            'cache_creation_cost': 0.000001875
        }

    def start_session(self, session_id: str | None = None):
        """开始新的追踪会话"""
        with self._lock:
            self._current_session = {
                'session_id': session_id or f"sess_{int(time.time())}",
                'start_time': time.time(),
                'calls': [],
                'total_input_tokens': 0,
                'total_output_tokens': 0,
                'total_cache_read_tokens': 0,
                'total_cache_creation_tokens': 0
            }

    def track_api_call(self, model: str, input_tokens: int = 0,
                       output_tokens: int = 0,
                       cache_read_tokens: int = 0,
                       cache_creation_tokens: int = 0,
                       endpoint: str = '', duration_ms: float = 0):
        """记录一次API调用"""
        call_record = {
            'timestamp': datetime.now().isoformat(),
            'model': model,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'cache_read_tokens': cache_read_tokens,
            'cache_creation_tokens': cache_creation_tokens,
            'endpoint': endpoint,
            'duration_ms': duration_ms,
            'estimated_cost_usd': self._estimate_cost(
                input_tokens, output_tokens,
                cache_read_tokens, cache_creation_tokens
            )
        }
        with self._lock:
            if self._current_session:
                self._current_session['calls'].append(call_record)
                self._current_session['total_input_tokens'] += input_tokens
                self._current_session['total_output_tokens'] += output_tokens
                self._current_session['total_cache_read_tokens'] += cache_read_tokens
                self._current_session['total_cache_creation_tokens'] += cache_creation_tokens

    def end_session(self) -> dict | None:
        """结束当前会话并返回统计"""
        with self._lock:
            if self._current_session:
                session = dict(self._current_session)
                session['end_time'] = time.time()
                session['duration_seconds'] = session['end_time'] - session['start_time']
                session['total_cost_usd'] = self._estimate_cost(
                    session['total_input_tokens'],
                    session['total_output_tokens'],
                    session['total_cache_read_tokens'],
                    session['total_cache_creation_tokens']
                )
                session['call_count'] = len(session['calls'])
                self._session_costs.append(session)
                self._current_session = None
                return session
            return None

    def _estimate_cost(self, input_t: int, output_t: int,
                      cache_read_t: int, cache_create_t: int) -> float:
        return round(
            input_t * self.pricing['input_token_cost']
            + output_t * self.pricing['output_token_cost']
            + cache_read_t * self.pricing['cache_read_cost']
            + cache_create_t * self.pricing['cache_creation_cost'],
            6
        )

    def get_current_session_stats(self) -> dict | None:
        """获取当前会话统计"""
        with self._lock:
            if self._current_session:
                return {
                    **{k: v for k, v in self._current_session.items() if k != 'calls'},
                    'call_count': len(self._current_session['calls']),
                    'running_seconds': time.time() - self._current_session['start_time'],
                    'estimated_cost_so_far': self._estimate_cost(
                        self._current_session['total_input_tokens'],
                        self._current_session['total_output_tokens'],
                        self._current_session['total_cache_read_tokens'],
                        self._current_session['total_cache_creation_tokens']
                    )
                }
            return None

    def get_total_stats(self) -> dict:
        """获取所有会话的累计统计"""
        with self._lock:
            total_cost = sum(s.get('total_cost_usd', 0) for s in self._session_costs)
            total_calls = sum(len(s.get('calls', [])) for s in self._session_costs)
            return {
                'total_sessions': len(self._session_costs),
                'total_calls': total_calls,
                'total_cost_usd': round(total_cost, 4),
                'active_session': self._current_session is not None
            }


cost_tracker = CostTracker()


class SkillHotReloader:
    """
    技能热加载器 (借鉴 Claude CLI 的 skillChangeDetector)

    监控文件变更，自动重新加载技能定义。
    """

    FILE_STABILITY_THRESHOLD_MS = 1000
    RELOAD_DEBOUNCE_MS = 300

    def __init__(self, watch_paths: list[str] = None):
        self.watch_paths = watch_paths or ['.trae/rules', '.trae/skills']
        self._last_reload = 0.0
        self._pending_changes = False
        self._callbacks: list[Callable] = []
        self._loaded_skills: dict[str, float] = {}

    def register_callback(self, callback: Callable):
        """注册技能变更回调"""
        self._callbacks.append(callback)

    def notify_change(self, skill_path: str):
        """通知文件变更"""
        now = time.time()
        self._loaded_skills[skill_path] = now
        self._pending_changes = True

    def check_and_reload(self) -> bool:
        """检查并执行热加载（应定期调用）"""
        if not self._pending_changes:
            return False
        now = time.time()
        if now - self._last_reload < self.RELOAD_DEBOUNCE_MS / 1000:
            return False
        if any(now - mtime < self.FILE_STABILITY_THRESHOLD_MS / 1000
               for mtime in self._loaded_skills.values()):
            return False
        self._pending_changes = False
        self._last_reload = now
        for cb in self._callbacks:
            try:
                cb(self._loaded_skills)
            except Exception as e:
                logger.error(f"技能热加载回调失败: {e}")
        return True

    def get_loaded_skills(self) -> dict[str, float]:
        return dict(self._loaded_skills)


skill_hot_reloader = SkillHotReloader()
