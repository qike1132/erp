"""容器（composition root）测试。

═══════════════════════════════════════════════════════════════════
为什么容器需要独立测试
═══════════════════════════════════════════════════════════════════

`container.py` 是整个架构里**唯一**同时 import adapters 与 application
的文件。别的文件错了有门禁兜底（纯度门禁、反向门禁），容器错了没有 ——
它是「被信任的例外」。

而它的失败模式又特别隐蔽：
    · 装配出错误的实现（比如把 metrics 装成假的永远 0% 的对象）
    · 单例被 rebuild 后悄悄失效（订阅者丢了，且不报错）
    · 构造期做了 I/O，于是「装配失败」变成一个无法归因的启动崩溃

这些都不是「函数返回错值」那类 bug，而是**装配关系**错了。
所以这里测的是关系与契约，不是业务逻辑：

    1. 每个 Protocol 装配到的是**预期的具体实现**（不是碰巧实现了同名方法）
    2. 降级语义正确 —— 不可用就是 None，绝不用假实现冒充
    3. 单例语义 —— session / event_bus 跨 rebuild 保持身份
    4. 容器**不做 I/O** —— 装配本身不读写文件
    5. 装配出的 Deps 真的**满足**各 Protocol（鸭子类型自检）
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from server_manager_v8.container import (  # noqa: E402
    AUDIT_FILENAME,
    CONFIG_CANDIDATES,
    Container,
    DEFAULT_PORTS,
    Environment,
    apply_config,
    build_container,
    probe_environment,
    resolve_config_path,
)
from server_manager_v8.domain.permissions import Role  # noqa: E402


# ═══════════════════════════════════════════════════════════════════
# 装配正确性
# ═══════════════════════════════════════════════════════════════════


class TestBuildContainer:
    def test_returns_container_with_deps(self, tmp_path):
        c = build_container(base_dir=tmp_path)
        assert isinstance(c, Container)
        assert c.deps is not None

    def test_wires_expected_implementations(self, tmp_path):
        """每个字段装配到的应是**特定**实现类，而非任意能凑合的对象。"""
        from server_manager_v8.adapters.audit_jsonl import JsonlAuditLog
        from server_manager_v8.adapters.clock import SystemClock
        from server_manager_v8.adapters.metrics_psutil import PsutilMetrics
        from server_manager_v8.adapters.notify_win import WinNotifier
        from server_manager_v8.adapters.port_impls import (
            HttpHealth, JsonStorage, NssmService, WinProcess,
        )

        c = build_container(base_dir=tmp_path)
        assert isinstance(c.deps.clock, SystemClock)
        assert isinstance(c.deps.service, NssmService)
        assert isinstance(c.deps.process, WinProcess)
        assert isinstance(c.deps.health, HttpHealth)
        assert isinstance(c.deps.audit, JsonlAuditLog)
        assert isinstance(c.deps.storage, JsonStorage)
        # metrics 取决于 psutil 是否可用（见降级测试）；可用时必须是真实现
        if c.deps.metrics is not None:
            assert isinstance(c.deps.metrics, PsutilMetrics)
        if c.deps.notify is not None:
            assert isinstance(c.deps.notify, WinNotifier)

    def test_deps_satisfies_protocols(self, tmp_path):
        """鸭子类型自检：装配出来的对象必须真的能通过 isinstance 检查。

        ★ 用 runtime_checkable Protocol 的 isinstance（只查方法存在性）——
          它抓不住「签名不匹配」，但能抓住「漏了一个方法」这类硬伤，
          而那恰好是薄包装类最容易犯的错。
        """
        from server_manager_v8.domain.ports import (
            AuditPort, ClockPort, HealthPort, ProcessPort,
            ServicePort, StoragePort,
        )

        c = build_container(base_dir=tmp_path)
        assert isinstance(c.deps.clock, ClockPort)
        assert isinstance(c.deps.service, ServicePort)
        assert isinstance(c.deps.process, ProcessPort)
        assert isinstance(c.deps.health, HealthPort)
        assert isinstance(c.deps.audit, AuditPort)
        assert isinstance(c.deps.storage, StoragePort)

    def test_accepts_overrides(self, tmp_path):
        c = build_container(
            base_dir=tmp_path, ports={'backend': 9999}, actor='tester',
            default_role=Role.ADMIN,
        )
        assert c.ports == {'backend': 9999}
        assert c.actor == 'tester'
        assert c.session.role is Role.ADMIN

    def test_default_ports_when_unspecified(self, tmp_path):
        c = build_container(base_dir=tmp_path)
        assert c.ports == DEFAULT_PORTS

    def test_default_role_is_viewer(self, tmp_path):
        """默认角色必须是**最低**权限 —— 启动即管理员是危险的默认值。"""
        c = build_container(base_dir=tmp_path)
        assert c.session.role is Role.VIEWER


# ═══════════════════════════════════════════════════════════════════
# ★ 容器不做 I/O
# ═══════════════════════════════════════════════════════════════════


class TestContainerDoesNoIO:
    def test_build_creates_no_files(self, tmp_path):
        """装配不应产生任何文件（尤其是配置文件与审计日志）。

        ★ 这条很重要：若装配期就把默认配置落盘，用户第一次启动
          （只是想看看）就凭空多出一个文件；更糟的是「配置不存在」
          这个状态被永久掩盖，之后无法区分「用户没配」与「配了但被重置」。
        """
        build_container(base_dir=tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_build_does_not_read_missing_config(self, tmp_path):
        """配置文件不存在时装配仍应成功（不能抛异常）。"""
        c = build_container(base_dir=tmp_path)
        assert c.config_path.exists() is False
        assert c.env.config_exists is False

    def test_audit_path_is_derived_not_created(self, tmp_path):
        c = build_container(base_dir=tmp_path)
        assert c.audit_path.name == AUDIT_FILENAME
        assert not c.audit_path.exists()


# ═══════════════════════════════════════════════════════════════════
# 降级语义
# ═══════════════════════════════════════════════════════════════════


class TestDegradation:
    def test_metrics_none_when_psutil_missing(self, tmp_path):
        """★ psutil 缺失时必须给 None，**不能**给一个返回 0% 的假对象。

        「0% CPU」和「测不到 CPU」是完全不同的两件事，
        后者被显示成 0% 会被读成「系统很空闲」—— 这是安全事故级的误导。
        """
        env = Environment(has_psutil=False)
        c = build_container(base_dir=tmp_path, env=env)
        assert c.deps.metrics is None

    def test_metrics_present_when_psutil_available(self, tmp_path):
        env = Environment(has_psutil=True)
        c = build_container(base_dir=tmp_path, env=env)
        assert c.deps.metrics is not None
        assert c.deps.metrics.available() is True

    def test_notify_always_present_but_degraded(self, tmp_path):
        """通知与指标不同：它有多级降级链，所以**总是**给一个真实对象。

        ★ 无 webview 时禁掉 messagebox 回退 —— 否则在无 GUI 环境
          会弹出阻塞式对话框，把启动流程卡死。
        """
        env = Environment(has_webview=False)
        c = build_container(base_dir=tmp_path, env=env)
        assert c.deps.notify is not None

    def test_degraded_notes_reports_reasons(self, tmp_path):
        env = Environment(
            has_psutil=False, has_webview=False,
            notes=['psutil 不可用：无法采集 CPU / 内存指标（不会以 0% 冒充）'],
        )
        c = build_container(base_dir=tmp_path, env=env)
        notes = c.degraded_notes()
        assert any('psutil' in n for n in notes)

    def test_degraded_notes_no_duplicates(self, tmp_path):
        """★ 探测已覆盖的能力不应再按 None 重复报一遍。

        重复告警会让用户以为有两个问题，进而去排查一个不存在的问题。
        """
        env = Environment(
            has_psutil=False, has_webview=False,
            notes=['psutil 不可用：无法采集 CPU / 内存指标（不会以 0% 冒充）',
                   'pywebview 不可用：系统通知将回退为日志记录'],
        )
        c = build_container(base_dir=tmp_path, env=env)
        notes = c.degraded_notes()
        assert len(notes) == 2, f'不应有重复：{notes}'

    def test_storage_always_present(self, tmp_path):
        """StoragePort 总是装配（配置读不到是**运行时**的事，不是装配期）。

        ★ 与 metrics 的区别：metrics 缺的是**能力**（没 psutil 就是没有），
          storage 缺的是**数据**（文件不存在而已，端口本身可用）。
          所以 storage 给 None 会让「首次运行」变成一堆 None 检查。
        """
        env = Environment(has_psutil=False)
        c = build_container(base_dir=tmp_path, env=env)
        assert c.deps.storage is not None


# ═══════════════════════════════════════════════════════════════════
# ★ 单例语义
# ═══════════════════════════════════════════════════════════════════


class TestSingletonSemantics:
    def test_session_and_bus_shared_within_container(self, tmp_path):
        """Session 与 EventBus 必须是同一批对象 —— 会话事件要走同一条总线。"""
        c = build_container(base_dir=tmp_path)
        assert c.session is not None
        assert c.event_bus is not None
        assert c.deps.event_bus is c.event_bus

    def test_apply_config_preserves_event_bus(self, tmp_path):
        """★ 配置变更重建容器时，EventBus 必须**复用**。

        换成新总线意味着所有订阅者静默失效 —— 而 emit 到空总线是合法操作，
        不报任何错。表现为「配置改完之后 UI 再也不刷新了」，
        且没有任何日志线索。
        """
        c1 = build_container(base_dir=tmp_path)
        c2 = apply_config(c1, {'api_port': 8123})
        assert c2.event_bus is c1.event_bus

    def test_apply_config_preserves_subscriptions(self, tmp_path):
        """更直接地验证：重建后订阅仍然收得到事件。"""
        from server_manager_v8.application.event_bus import EventBus

        c1 = build_container(base_dir=tmp_path)
        seen: list[str] = []

        class FakeEvent:
            kind = 'fake'

        bus = c1.event_bus
        bus.subscribe(FakeEvent, lambda ev: seen.append('hit'))

        c2 = apply_config(c1, {'api_port': 8123})
        c2.event_bus.emit(FakeEvent())
        assert seen == ['hit'], '重建后订阅失效了'

    def test_apply_config_produces_new_deps(self, tmp_path):
        """Deps 是 frozen —— 必须换新对象，不能原地改。"""
        c1 = build_container(base_dir=tmp_path)
        c2 = apply_config(c1, {'api_port': 8123})
        assert c2.deps is not c1.deps
        assert c2.deps.ports['backend'] == 8123
        assert c1.deps.ports['backend'] != 8123, '旧容器的 Deps 不应被改动'

    def test_apply_config_maps_port_keys(self, tmp_path):
        c = apply_config(
            build_container(base_dir=tmp_path),
            {'api_port': 1, 'web_port': 2, 'redis_port': 3},
        )
        assert c.ports == {'backend': 1, 'frontend': 2, 'redis': 3}

    def test_apply_config_maps_path_keys(self, tmp_path):
        c = apply_config(
            build_container(base_dir=tmp_path),
            {'redis_exe': '  C:/redis.exe  ', 'nssm_path': 'C:/nssm.exe'},
        )
        assert c.paths['redis_exe'] == 'C:/redis.exe'  # strip 过
        assert c.paths['nssm_path'] == 'C:/nssm.exe'

    def test_apply_config_ignores_bad_types(self, tmp_path):
        """非法类型不应导致崩溃，也不应污染 ports（保守跳过）。"""
        base = build_container(base_dir=tmp_path)
        c = apply_config(base, {'api_port': 'abc', 'web_port': None})
        assert c.ports['backend'] == base.ports['backend']
        assert c.ports['frontend'] == base.ports['frontend']

    def test_apply_config_ignores_blank_paths(self, tmp_path):
        """空字符串/空白路径视为「没填」，不应覆盖已有值。

        ★ 否则用户清空一个输入框再保存，就把路径配置抹掉了 ——
          而 UI 上「清空」和「不改」看起来是一样的。
        """
        base = build_container(base_dir=tmp_path, paths={'redis_exe': 'C:/r.exe'})
        c = apply_config(base, {'redis_exe': '   '})
        assert c.paths['redis_exe'] == 'C:/r.exe'


# ═══════════════════════════════════════════════════════════════════
# 环境探测
# ═══════════════════════════════════════════════════════════════════


class TestProbeEnvironment:
    def test_probe_is_immutable_report(self, tmp_path):
        """探测结果应是 frozen —— 防止「探测到一半」的状态被读到。"""
        env = probe_environment(tmp_path)
        with pytest.raises(Exception):
            env.has_psutil = True  # type: ignore[misc]

    def test_probe_reports_missing_config(self, tmp_path):
        env = probe_environment(tmp_path)
        assert env.config_exists is False
        assert env.degraded is True

    def test_probe_detects_existing_config(self, tmp_path):
        (tmp_path / 'erp_server_config.json').write_text('{}', encoding='utf-8')
        env = probe_environment(tmp_path)
        assert env.config_exists is True

    def test_probe_notes_explain_each_gap(self, tmp_path):
        """每条降级都要有**原因说明** —— 只说「不可用」等于让用户来问我们。"""
        env = probe_environment(tmp_path)
        for note in env.notes:
            assert len(note) > 8, f'降级说明太短，没有信息量：{note!r}'


class TestResolveConfigPath:
    def test_prefers_first_existing_candidate(self, tmp_path):
        first = CONFIG_CANDIDATES[0]
        (tmp_path / first).write_text('{}', encoding='utf-8')
        assert resolve_config_path(tmp_path).name == first

    def test_prefers_earlier_candidate_in_order(self, tmp_path):
        """两个候选都存在时，取**顺序在前**的那个（顺序即优先级）。"""
        for name in CONFIG_CANDIDATES[:2]:
            (tmp_path / name).write_text('{}', encoding='utf-8')
        assert resolve_config_path(tmp_path).name == CONFIG_CANDIDATES[0]

    def test_falls_back_to_first_candidate(self, tmp_path):
        """都不存在时返回首选候选（可写路径），而不是 None。

        返回 None 会迫使每个调用方再写一遍兜底，那才是重复。
        """
        got = resolve_config_path(tmp_path)
        assert got.name == CONFIG_CANDIDATES[0]
        assert got.parent == tmp_path


# ═══════════════════════════════════════════════════════════════════
# 与真实用例的集成
# ═══════════════════════════════════════════════════════════════════


class TestContainerWithUsecases:
    def test_configops_loads_via_container(self, tmp_path):
        """容器装配的 Deps 能直接驱动用例（端到端连通性）。"""
        from server_manager_v8.application.usecases.config_ops import ConfigOps

        c = build_container(base_dir=tmp_path, default_role=Role.ADMIN)
        res = ConfigOps(c.deps).load(session=c.session)
        assert res.ok is True

    def test_audit_port_is_writable_through_container(self, tmp_path):
        """通过容器装配的审计端口真的能写 —— 验证路径确实被接上了。"""
        from server_manager_v8.domain.results import AuditEntry, AuditOutcome

        c = build_container(base_dir=tmp_path, default_role=Role.ADMIN)
        entry = AuditEntry(
            ts=1.0, action='test.action', actor='tester',
            outcome=AuditOutcome.OK, detail='容器集成测试',
        )
        c.deps.audit.record(entry)
        entries = c.deps.audit.query(
            __import__(
                'server_manager_v8.domain.results', fromlist=['AuditFilter'],
            ).AuditFilter(),
        )
        assert any(e.action == 'test.action' for e in entries)
        # 确认真的落盘到了容器指定的位置
        assert c.audit_path.exists()

    def test_container_ports_visible_to_usecases(self, tmp_path):
        """端口配置要真的流进 Deps，用例读得到。"""
        from server_manager_v8.application.usecases.kill_port import default_ports

        c = build_container(base_dir=tmp_path, ports={'backend': 7777})
        assert c.deps.ports['backend'] == 7777
        # 领域层的默认端口表与容器默认值应一致（两处漂移过一次就很难查）
        d = default_ports()
        assert set(d) <= set(DEFAULT_PORTS) | {'redis'}


# ═══════════════════════════════════════════════════════════════════
# 层边界
# ═══════════════════════════════════════════════════════════════════


class TestLayerBoundary:
    def test_application_layer_never_imports_adapters(self):
        """★ 容器是**唯一**允许 import adapters 的非适配器文件。

        这条边界是四层架构的核心承诺，且它有实际代价：
        一旦破坏，用例就不能在无 Windows 的 CI 里跑（Fake 替换不了）。
        所以在此把它固化成断言 —— 它比门禁更直接（门禁查的是文件集合，
        这里查的是「除容器外没有任何 L3 文件碰 adapters」）。
        """
        import ast

        pkg = Path(__file__).resolve().parent.parent.parent / 'server_manager_v8'
        offenders: list[str] = []

        for path in (pkg / 'application').rglob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'), str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if 'adapters' in node.module:
                        offenders.append(f'{path.name}:{node.lineno} → {node.module}')
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if 'adapters' in alias.name:
                            offenders.append(f'{path.name}:{node.lineno} → {alias.name}')

        assert not offenders, (
            f'应用层文件违规 import adapters：\n' + '\n'.join(offenders)
        )

    def test_container_module_exists_and_is_reachable(self):
        """容器必须真能 import（防止名字写错导致的运行时才发现）。"""
        import importlib

        mod = importlib.import_module('server_manager_v8.container')
        assert hasattr(mod, 'build_container')
        assert hasattr(mod, 'probe_environment')
        assert hasattr(mod, 'apply_config')
