"""
轻量服务容器（Service Container）

为类服务（class-based services）提供统一的获取入口与可覆盖注册表，
让高层代码依赖"工厂/抽象"而非直接 import 模块级单例，改善 DIP。

设计原则：
- 不引入第三方 DI 框架，保持零依赖、轻量；
- 默认行为与现状完全一致（返回模块级单例），无破坏性变更；
- 提供 override/reset 钩子，测试可替换真实实现，无需 mock 模块属性。

用法（生产）：
    from fastapi_app.core.container import get_customer_search_service
    svc = get_customer_search_service()

用法（测试覆盖）：
    from fastapi_app.core import container
    container.override("customer_search", FakeSearchService())
    try:
        ...
    finally:
        container.reset("customer_search")
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# 显式覆盖实例注册表（测试用），name -> instance
_override_registry: dict[str, Any] = {}
# 默认工厂注册表，name -> factory()
_factories: dict[str, Callable[[], Any]] = {}
_lock = threading.RLock()


def register_factory(name: str, factory: Callable[[], Any]) -> None:
    """注册默认工厂。重复注册同名工厂时以最后一次为准并记录日志。"""
    with _lock:
        _factories[name] = factory


def get_service(name: str, factory: Callable[[], Any] | None = None) -> Any:
    """获取服务实例：优先返回 override 实例，其次按工厂解析。

    默认工厂由调用方传入（lambda 返回模块级单例），
    或由 register_factory 提前注册。未命中时抛出 KeyError。
    """
    with _lock:
        if name in _override_registry:
            return _override_registry[name]
    resolver = factory if factory is not None else _factories.get(name)
    if resolver is None:
        raise KeyError(f"未注册服务: {name}")
    return resolver()


def override(name: str, instance: Any) -> None:
    """测试钩子：用指定实例覆盖服务，直到 reset。"""
    with _lock:
        _override_registry[name] = instance


def reset(name: str) -> None:
    """移除指定服务的 override 覆盖。"""
    with _lock:
        _override_registry.pop(name, None)


def reset_all() -> None:
    """清空所有 override 覆盖（不影响已注册的默认工厂）。"""
    with _lock:
        _override_registry.clear()


# ---------------------------------------------------------------------------
# 便捷获取函数（业务服务）
# ---------------------------------------------------------------------------

def get_customer_search_service():
    """获取客户搜索服务（默认返回模块级单例，可被测试 override）。"""
    from fastapi_app.services.customer_search_service import customer_search_service
    return get_service("customer_search", lambda: customer_search_service)


def get_product_search_service():
    """获取产品搜索服务（默认返回模块级单例，可被测试 override）。"""
    from fastapi_app.services.product_search_service import product_search_service
    return get_service("product_search", lambda: product_search_service)


# ---------------------------------------------------------------------------
# 备份域服务（默认返回模块级单例，可被测试 override）
# ---------------------------------------------------------------------------

def get_backup_cleanup_service():
    """获取备份清理服务。"""
    from fastapi_app.services.backup.cleanup.service import cleanup_service
    return get_service("backup_cleanup", lambda: cleanup_service)


def get_backup_alert_service():
    """获取备份告警服务。"""
    from fastapi_app.services.backup.metrics.alert_service import alert_service
    return get_service("backup_alert", lambda: alert_service)


def get_backup_metrics_service():
    """获取备份指标服务。"""
    from fastapi_app.services.backup.metrics.service import metrics_service
    return get_service("backup_metrics", lambda: metrics_service)


def get_backup_policy_service():
    """获取备份策略服务。"""
    from fastapi_app.services.backup.orchestration.policy_service import policy_service
    return get_service("backup_policy", lambda: policy_service)


def get_backup_recovery_test_service():
    """获取灾备演练服务。"""
    from fastapi_app.services.backup.orchestration.recovery_test_service import recovery_test_service
    return get_service("backup_recovery_test", lambda: recovery_test_service)


def get_backup_health_check_service():
    """获取备份健康检查服务。"""
    from fastapi_app.services.backup.verify.health_check_service import health_check_service
    return get_service("backup_health_check", lambda: health_check_service)
