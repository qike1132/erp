"""models 模块单测。"""

from __future__ import annotations

import pytest

from server_manager_v8.domain.models import (
    DEFAULT_REDIS_SERVICES,
    DEPENDENCY_CANDIDATES,
    MANAGED_NSSM_SERVICES,
    NSSM_SERVICES,
    SERVICE_API,
    SERVICE_ARQ,
    SERVICE_REDIS,
    SVC_API,
    SVC_ARQ,
    Dependency,
    HealthProbe,
    ProbeKind,
    ProcessRef,
    ProcessRole,
    RunMode,
    Service,
    ServiceKind,
    ServiceSnapshot,
    build_probes,
    detect_dependencies,
    probes_for_service,
)
from server_manager_v8.domain.service_state import ServiceStatus


class TestServiceConstants:
    def test_service_names_match_legacy(self):
        """★ 服务名必须与原 _SVC_API / _SVC_ARQ 一致。"""
        assert SVC_API == 'erp-prod'
        assert SVC_ARQ == 'erp-arq'
        assert NSSM_SERVICES == ('erp-prod', 'erp-arq')

    def test_redis_services_match_legacy(self):
        """★ 必须与原 _DEFAULT_REDIS_SERVICES 一致。"""
        assert DEFAULT_REDIS_SERVICES == ('erp-redis', 'erp-redis-broker')


class TestServiceKind:
    def test_nssm_kind(self):
        assert SERVICE_API.is_nssm is True
        assert SERVICE_ARQ.is_nssm is True

    def test_native_kind(self):
        """★ Redis 是原生服务 —— guard 对它无效（D6 语义）。"""
        assert SERVICE_REDIS.is_nssm is False

    def test_str(self):
        assert str(SERVICE_API) == 'erp-prod'

    def test_managed_tuples(self):
        assert len(MANAGED_NSSM_SERVICES) == 2
        assert all(s.is_nssm for s in MANAGED_NSSM_SERVICES)


class TestService:
    def test_rejects_empty_name(self):
        with pytest.raises(ValueError):
            Service('')

    def test_frozen(self):
        with pytest.raises(Exception):
            SERVICE_API.name = 'x'  # type: ignore[misc]


class TestHealthProbe:
    def test_build_probes_urls(self):
        """★ URL 必须与原 _wait_service_running 的硬编码一致。"""
        probes = build_probes(5002, 3000)
        by_name = {p.name: p for p in probes}
        assert by_name['api'].url == 'http://127.0.0.1:5002/api/health'
        assert by_name['web'].url == 'http://127.0.0.1:3000/nginx-health'

    def test_build_probes_rejects_bad_ports(self):
        with pytest.raises(ValueError):
            build_probes(0, 3000)
        with pytest.raises(ValueError):
            build_probes(5002, 99999)

    def test_http_probe_requires_url(self):
        with pytest.raises(ValueError):
            HealthProbe('x', ProbeKind.HTTP, url='')

    def test_probes_for_api_includes_web(self):
        """erp-prod 承载 API 与 nginx，需要两项探针。"""
        probes = probes_for_service(SVC_API, 5002, 3000)
        assert {p.name for p in probes} == {'api', 'web'}

    def test_probes_for_arq_excludes_web(self):
        """★ 迁移 `need_web = name == _SVC_API` 语义：erp-arq 不需要 nginx 探针。"""
        probes = probes_for_service(SVC_ARQ, 5002, 3000)
        assert {p.name for p in probes} == {'api'}


class TestProcessRef:
    def test_valid(self):
        p = ProcessRef(pid=1234, role=ProcessRole.BACKEND)
        assert p.label == '后端'

    def test_custom_name_overrides_label(self):
        p = ProcessRef(pid=1, role=ProcessRole.BACKEND, name='uvicorn worker')
        assert p.label == 'uvicorn worker'

    @pytest.mark.parametrize('bad', [0, -1, '1234', None])
    def test_rejects_invalid_pid(self, bad):
        with pytest.raises(ValueError):
            ProcessRef(pid=bad, role=ProcessRole.BACKEND)

    def test_role_labels_are_chinese(self):
        """★ 角色标签必须保留原实现的 UI 文案。"""
        assert ProcessRole.BACKEND.label == '后端'
        assert ProcessRole.FRONTEND.label == '前端'
        assert ProcessRole.PROD_RUNNER.label == 'prod_runner'


class TestDependency:
    def test_valid(self):
        d = Dependency(service=SVC_API, depends_on=('erp-redis',))
        assert d.depends_on == ('erp-redis',)

    def test_rejects_empty_service(self):
        with pytest.raises(ValueError):
            Dependency(service='')

    def test_detect_returns_none_when_nothing_installed(self):
        """原实现无依赖时不写 DependOnService。"""
        assert detect_dependencies(frozenset()) is None

    def test_detect_finds_redis(self):
        d = detect_dependencies({'erp-redis', 'unrelated-service'})
        assert d is not None
        assert d.depends_on == ('erp-redis',)
        assert d.service == SVC_API

    def test_detect_preserves_candidate_order(self):
        """★ 依赖顺序须按 DEPENDENCY_CANDIDATES 的声明顺序（决定启动顺序）。"""
        d = detect_dependencies({'Redis', 'erp-redis', 'postgresql-x64-16'})
        assert d is not None
        assert d.depends_on == ('postgresql-x64-16', 'erp-redis', 'Redis')

    def test_detect_postgres(self):
        d = detect_dependencies({'postgresql-x64-16'})
        assert d is not None and d.depends_on == ('postgresql-x64-16',)

    def test_candidates_include_known_services(self):
        for name in ('erp-redis', 'erp-redis-broker', 'Memurai', 'Redis'):
            assert name in DEPENDENCY_CANDIDATES


class TestRunMode:
    def test_values_match_legacy(self):
        """★ 值必须与原 _mode 的字符串一致。"""
        assert RunMode.NONE.value == 'none'
        assert RunMode.DUAL_DEV.value == 'dual_dev'
        assert RunMode.PROD.value == 'prod'

    def test_labels(self):
        assert RunMode.NONE.label == '未运行'
        assert RunMode.DUAL_DEV.label == '开发模式'
        assert RunMode.PROD.label == '生产模式'

    def test_conflicts(self):
        """★ 双模式互斥关系。"""
        assert RunMode.DUAL_DEV.conflicts_with is RunMode.PROD
        assert RunMode.PROD.conflicts_with is RunMode.DUAL_DEV
        assert RunMode.NONE.conflicts_with is None


class TestServiceSnapshot:
    def test_running(self):
        s = ServiceSnapshot(SVC_API, ServiceStatus.RUNNING, '4 RUNNING', 1234)
        assert s.is_running is True
        assert s.blocks_switch is True

    def test_unknown_blocks(self):
        """★ 未知必须阻断切换（互杀事故防线）。"""
        s = ServiceSnapshot(SVC_API, ServiceStatus.UNKNOWN, '未知')
        assert s.blocks_switch is True

    def test_stopped_and_absent_do_not_block(self):
        assert ServiceSnapshot('x', ServiceStatus.STOPPED).blocks_switch is False
        assert ServiceSnapshot('x', ServiceStatus.ABSENT).blocks_switch is False
