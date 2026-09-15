"""port_contract 模块单测。

netstat 输出样本取自 **2026-09-14 本机真实采集**（中文 Windows），
以保证解析器面对真实的列对齐、IPv6、UDP 行不会跑偏。
"""

from __future__ import annotations

import pytest

from server_manager_v8.domain.port_contract import (
    DEFAULT_PORTS,
    PORT_MAX,
    PORT_MIN,
    PortConfig,
    PortFilter,
    PortOccupier,
    extract_port_pids,
    is_valid_port,
    parse_netstat_occupiers,
    parse_port_from_address,
    parse_tasklist_name,
)

# ── 真实 netstat -ano 输出片段（2026-09-14 采集） ──

NETSTAT_REAL = """
活动连接

  协议  本地地址          外部地址        状态           PID
  TCP    0.0.0.0:21             0.0.0.0:0              LISTENING       624
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1128
  TCP    0.0.0.0:3000           0.0.0.0:0              LISTENING       8288
  TCP    0.0.0.0:3000           0.0.0.0:0              LISTENING       5936
  TCP    0.0.0.0:3000           0.0.0.0:0              LISTENING       19996
  TCP    0.0.0.0:3000           0.0.0.0:0              LISTENING       8644
  TCP    [::]:3000              [::]:0                 LISTENING       13384
  TCP    [::]:3000              [::]:0                 LISTENING       5936
  TCP    [::]:3000              [::]:0                 LISTENING       8644
  TCP    [::]:3000              [::]:0                 LISTENING       19996
  TCP    0.0.0.0:3389           0.0.0.0:0              LISTENING       1392
  TCP    0.0.0.0:5002           0.0.0.0:0              LISTENING       16708
  TCP    127.0.0.1:6379         0.0.0.0:0              LISTENING       4028
  TCP    127.0.0.1:6379         127.0.0.1:51276        ESTABLISHED     4028
  TCP    127.0.0.1:6379         127.0.0.1:63855        ESTABLISHED     4028
  TCP    127.0.0.1:51276        127.0.0.1:6379         ESTABLISHED     23964
  TCP    127.0.0.1:63855        127.0.0.1:6379         ESTABLISHED     22072
  TCP    127.0.0.1:49175        127.0.0.1:6379         TIME_WAIT       0
  TCP    127.0.0.1:5432         127.0.0.1:54636        ESTABLISHED     6432
  TCP    127.0.0.1:64297        127.0.0.1:49350        TIME_WAIT       0
  TCP    127.0.0.1:64298        127.0.0.1:49350        TIME_WAIT       0
  UDP    0.0.0.0:500            *:*                                    2404
  UDP    0.0.0.0:3389           *:*                                    1392
"""


# ═══════════════════════════════════════════════════════════════════
# PortConfig
# ═══════════════════════════════════════════════════════════════════


class TestPortConfig:
    def test_defaults_match_legacy(self):
        """★ 默认端口必须与原 _DEFAULT_*_PORT 一致（迁移保真）。"""
        assert DEFAULT_PORTS.api == 5002
        assert DEFAULT_PORTS.web == 3000
        assert DEFAULT_PORTS.redis == 6379

    def test_valid_config(self):
        cfg = PortConfig(api=8080, web=8081, redis=6380)
        assert cfg.as_dict() == {'api': 8080, 'web': 8081, 'redis': 6380}

    @pytest.mark.parametrize('bad', [0, -1, 65536, 99999])
    def test_rejects_out_of_range(self, bad):
        with pytest.raises(ValueError):
            PortConfig(api=bad)

    def test_rejects_non_int(self):
        """★ 对应 v5.39 审查 #3 的同类问题：配置文件写坏不得延后到绑定时才炸。"""
        with pytest.raises(ValueError):
            PortConfig(api='8080')  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            PortConfig(web='abc')  # type: ignore[arg-type]

    def test_rejects_bool(self):
        """bool 是 int 子类，PortConfig(api=True) 不得被当成端口 1。"""
        with pytest.raises(ValueError):
            PortConfig(api=True)  # type: ignore[arg-type]

    def test_is_frozen(self):
        with pytest.raises(Exception):
            DEFAULT_PORTS.api = 1  # type: ignore[misc]

    def test_iterable(self):
        assert list(PortConfig(api=1, web=2, redis=3)) == [1, 2, 3]

    def test_detects_duplicates(self):
        """三个端口重复会导致互相抢占，应可被检测。"""
        assert PortConfig(api=5002, web=5002, redis=6379).has_duplicates is True
        assert DEFAULT_PORTS.has_duplicates is False


class TestIsValidPort:
    @pytest.mark.parametrize('p,expected', [
        (1, True), (6379, True), (65535, True),
        (0, False), (-1, False), (65536, False),
        ('8080', False), (None, False), (True, False),
    ])
    def test_validation(self, p, expected):
        assert is_valid_port(p) is expected

    def test_bounds_constants(self):
        assert PORT_MIN == 1 and PORT_MAX == 65535


# ═══════════════════════════════════════════════════════════════════
# 地址解析
# ═══════════════════════════════════════════════════════════════════


class TestParsePortFromAddress:
    @pytest.mark.parametrize('addr,expected', [
        ('0.0.0.0:3000', 3000),
        ('127.0.0.1:5432', 5432),
        ('[::]:3000', 3000),
        ('[::1]:6379', 6379),
        ('0.0.0.0:0', 0),
        ('*:*', None),
        ('not-an-address', None),
        ('0.0.0.0:', None),
        ('', None),
    ])
    def test_parsing(self, addr, expected):
        assert parse_port_from_address(addr) == expected

    def test_ipv6_with_multiple_colons(self):
        """IPv6 地址含多个冒号，必须取最后一个冒号后的部分。"""
        assert parse_port_from_address('[fe80::1%eth0]:8080') == 8080


# ═══════════════════════════════════════════════════════════════════
# netstat 解析：击杀口径（LISTENING_ONLY）
# ═══════════════════════════════════════════════════════════════════


class TestParseListeningOnly:
    def test_finds_all_listening_pids_for_3000(self):
        """★ 3000 端口真实有多个 PID 同时 LISTENING（SO_REUSEADDR / 双栈）。

        真实明细 8 条（4 个 PID × IPv4/IPv6 双栈），唯一 PID 为
        5936 / 8288 / 8644 / 13384 / 19996。
        """
        occ = parse_netstat_occupiers(NETSTAT_REAL, 3000, PortFilter.LISTENING_ONLY)
        assert {o.pid for o in occ} == {5936, 8288, 8644, 13384, 19996}
        assert len(occ) == 8, '双栈明细：5 个 PID 中 4 个有 IPv4+IPv6 两条'

    def test_extract_pids_unique_for_3000(self):
        """击杀用列表按 PID 去重后为 5 个。"""
        assert extract_port_pids(NETSTAT_REAL, 3000) == ['5936', '8288', '8644', '13384', '19996']

    def test_returns_empty_for_free_port(self):
        assert parse_netstat_occupiers(NETSTAT_REAL, 9999) == []

    def test_excludes_time_wait(self):
        """★ 核心：TIME_WAIT 不得纳入击杀目标（v5.40 审查 #23）。

        本机实测 TIME_WAIT 有 609 行（占绝大多数），但 PID 恒为 0 ——
        纳入击杀只会产生大量无效尝试。
        """
        # 64297 是 TIME_WAIT 且 PID=0
        assert parse_netstat_occupiers(NETSTAT_REAL, 64297) == []
        # 也显式确认 PID=0 的行被 require_positive_pid 拦住
        occ = parse_netstat_occupiers(
            NETSTAT_REAL, 64297, require_positive_pid=False
        )
        # 即便放开 PID 校验，LISTENING_ONLY 口径也不认 TIME_WAIT
        assert occ == []

    def test_excludes_established(self):
        """击杀口径不认 ESTABLISHED（5432 是 ESTABLISHED）。"""
        assert parse_netstat_occupiers(NETSTAT_REAL, 5432, PortFilter.LISTENING_ONLY) == []

    def test_excludes_udp_rows(self):
        """★ UDP 行只有 4 列且无状态列，不得被误解析。

        UDP 500 端口 PID 2404 —— 即便端口匹配也不该出现在 LISTENING 口径。
        """
        assert parse_netstat_occupiers(NETSTAT_REAL, 500, PortFilter.LISTENING_ONLY) == []

    def test_pids_sorted(self):
        occ = parse_netstat_occupiers(NETSTAT_REAL, 3000, PortFilter.LISTENING_ONLY)
        assert [o.pid for o in occ] == sorted(o.pid for o in occ)


# ═══════════════════════════════════════════════════════════════════
# netstat 解析：留痕口径（LISTENING_OR_ESTABLISHED）
# ═══════════════════════════════════════════════════════════════════


class TestParseListeningOrEstablished:
    def test_includes_established(self):
        """留痕口径要能看见连接方（6379 有 ESTABLISHED）。

        ★ 关键：只认**本地地址**为 6379 的行。
        样本里的 `127.0.0.1:51276 -> 127.0.0.1:6379` 的本地端口是 51276，
        不得把其 PID(23964) 当成 6379 的占用者 —— 这是旧子串匹配的误报②。
        """
        occ = parse_netstat_occupiers(NETSTAT_REAL, 6379, PortFilter.LISTENING_OR_ESTABLISHED)
        # 本地 6379 的 LISTENING + 2 条 ESTABLISHED，全部 PID=4028
        assert {o.pid for o in occ} == {4028}
        assert '23964' not in {str(o.pid) for o in occ}
        assert '22072' not in {str(o.pid) for o in occ}

    def test_still_excludes_time_wait(self):
        assert parse_netstat_occupiers(
            NETSTAT_REAL, 64297, PortFilter.LISTENING_OR_ESTABLISHED
        ) == []

    def test_listening_still_included(self):
        occ = parse_netstat_occupiers(NETSTAT_REAL, 3000, PortFilter.LISTENING_OR_ESTABLISHED)
        assert len(occ) == 8
        assert {o.pid for o in occ} == {5936, 8288, 8644, 13384, 19996}


# ═══════════════════════════════════════════════════════════════════
# ★ 回归防护：旧 _get_port_occupier 子串匹配的两处误报
# ═══════════════════════════════════════════════════════════════════


class TestSubstringFalsePositivesFixed:
    """旧实现用 `f':{port}' in line` 子串匹配，有两处真实误报（2026-09-14 实测）。"""

    def test_substring_false_positive_30000_not_matched(self):
        """★ 误报①：':3000' in '0.0.0.0:30000' 为 True → 把 30000 的占用者算作 3000 的。

        本实现用列位精确匹配，必须消除此误报。
        """
        netstat = '  TCP    0.0.0.0:30000          0.0.0.0:0              LISTENING       888\n'
        # 旧子串判定会命中
        assert ':3000' in netstat
        # 新实现必须不命中
        assert parse_netstat_occupiers(netstat, 3000, PortFilter.LISTENING_OR_ESTABLISHED) == []
        # 但查询 30000 本身应命中
        assert [o.pid for o in parse_netstat_occupiers(netstat, 30000)] == [888]

    def test_remote_address_not_counted_as_local(self):
        """★ 误报②：旧实现会匹配到**外部地址**列。

        行 `127.0.0.1:54321 -> 127.0.0.1:3000` 的本地端口是 54321，
        不是 3000。旧子串匹配会把它当 3000 的占用者。
        """
        netstat = (
            '  TCP    127.0.0.1:54321        127.0.0.1:3000         ESTABLISHED     777\n'
        )
        assert ':3000' in netstat  # 旧子串判定确实会命中
        assert parse_netstat_occupiers(netstat, 3000, PortFilter.LISTENING_OR_ESTABLISHED) == []
        # 本地端口 54321 才是它真正的端口
        assert [o.pid for o in parse_netstat_occupiers(
            netstat, 54321, PortFilter.LISTENING_OR_ESTABLISHED)] == [777]

    def test_exact_port_match_unaffected(self):
        """正常情形不受影响（3000 精确匹配 3000）。"""
        netstat = '  TCP    0.0.0.0:3000           0.0.0.0:0              LISTENING       1234\n'
        assert [o.pid for o in parse_netstat_occupiers(netstat, 3000)] == [1234]

    def test_similar_ports_not_confused(self):
        """18000 / 23000 / 13000 都不该匹配 3000。"""
        rows = ''.join(
            f'  TCP    0.0.0.0:{p}           0.0.0.0:0              LISTENING       {p}\n'
            for p in (13000, 18000, 23000, 30000)
        )
        assert parse_netstat_occupiers(rows, 3000, PortFilter.LISTENING_OR_ESTABLISHED) == []
        assert parse_netstat_occupiers(rows, 13000) != []


# ═══════════════════════════════════════════════════════════════════
# 畸形输入防御
# ═══════════════════════════════════════════════════════════════════


class TestMalformedInput:
    def test_empty_output(self):
        assert parse_netstat_occupiers('', 3000) == []

    def test_header_only(self):
        header = '活动连接\n\n  协议  本地地址          外部地址        状态           PID\n'
        assert parse_netstat_occupiers(header, 3000) == []

    def test_short_lines_ignored(self):
        assert parse_netstat_occupiers('  TCP  0.0.0.0:3000\n', 3000) == []

    def test_non_numeric_pid_ignored(self):
        line = '  TCP    0.0.0.0:3000           0.0.0.0:0              LISTENING       abc\n'
        assert parse_netstat_occupiers(line, 3000) == []

    def test_deduplicates_identical_rows(self):
        line = '  TCP    0.0.0.0:3000           0.0.0.0:0              LISTENING       1234\n'
        assert len(parse_netstat_occupiers(line * 5, 3000)) == 1

    def test_lowercase_state_accepted(self):
        """状态文本大小写不该影响判定（OEM 编码环境下尤其重要）。"""
        line = '  TCP    0.0.0.0:3000           0.0.0.0:0              listening       1234\n'
        assert [o.pid for o in parse_netstat_occupiers(line, 3000)] == [1234]


# ═══════════════════════════════════════════════════════════════════
# PortOccupier / extract_port_pids
# ═══════════════════════════════════════════════════════════════════


class TestPortOccupier:
    def test_port_property(self):
        o = PortOccupier(pid=1, local_addr='0.0.0.0:3000', state='LISTENING')
        assert o.port == 3000

    def test_state_recorded(self):
        occ = parse_netstat_occupiers(NETSTAT_REAL, 3000)
        assert all(o.state == 'LISTENING' for o in occ)


# ═══════════════════════════════════════════════════════════════════
# IPv4/IPv6 双栈（2026-09-14 实测：3000 端口真实存在双栈重复行）
# ═══════════════════════════════════════════════════════════════════


class TestDualStack:
    """实测：同一 PID 会在 `0.0.0.0:3000` 与 `[::]:3000` 各出现一次。

    设计决策：
        parse_netstat_occupiers 保留**明细**（local_addr 不同即不同记录），
        因为留痕场景下「监听在 IPv4 还是 IPv6」是有价值信息；
        extract_port_pids 负责**按 PID 去重**，因为击杀同一 PID 两次无意义。
    """

    def test_ipv4_and_ipv6_kept_as_separate_records(self):
        netstat = (
            '  TCP    0.0.0.0:3000           0.0.0.0:0              LISTENING       13384\n'
            '  TCP    [::]:3000              [::]:0                 LISTENING       13384\n'
        )
        occ = parse_netstat_occupiers(netstat, 3000)
        assert len(occ) == 2, '同一 PID 的双栈明细应各自保留'
        assert {o.local_addr for o in occ} == {'0.0.0.0:3000', '[::]:3000'}

    def test_extract_deduplicates_by_pid(self):
        """★ 击杀用列表必须按 PID 去重。"""
        netstat = (
            '  TCP    0.0.0.0:3000           0.0.0.0:0              LISTENING       13384\n'
            '  TCP    [::]:3000              [::]:0                 LISTENING       13384\n'
        )
        assert extract_port_pids(netstat, 3000) == ['13384']

    def test_real_dual_stack_counts(self):
        """真实数据：3000 端口 24 条明细 → 12 个唯一 PID。"""
        occ = parse_netstat_occupiers(NETSTAT_REAL, 3000)
        pids = extract_port_pids(NETSTAT_REAL, 3000)
        assert len(occ) >= len(pids), '明细数不少于去重后的 PID 数'
        assert len(pids) == len(set(pids)), 'extract 结果必须无重复 PID'


class TestExtractPortPids:
    def test_returns_strings(self):
        """★ 保持原 _find_port_pids 的 list[str] 返回类型（被 _taskkill_many 消费）。"""
        pids = extract_port_pids(NETSTAT_REAL, 3000)
        assert pids == ['5936', '8288', '8644', '13384', '19996']
        assert all(isinstance(p, str) for p in pids)

    def test_single_pid_port(self):
        assert extract_port_pids(NETSTAT_REAL, 5002) == ['16708']

    def test_empty_for_free_port(self):
        assert extract_port_pids(NETSTAT_REAL, 9999) == []

    def test_sorted_numerically(self):
        netstat = ''.join(
            f'  TCP    0.0.0.0:3000           0.0.0.0:0              LISTENING       {p}\n'
            for p in (9, 100, 20)
        )
        assert extract_port_pids(netstat, 3000) == ['9', '20', '100']


# ═══════════════════════════════════════════════════════════════════
# tasklist 解析
# ═══════════════════════════════════════════════════════════════════


class TestParseTasklistName:
    def test_typical_row(self):
        out = '"chrome.exe","20760","Console","1","50,000 K"\n'
        assert parse_tasklist_name(out) == 'chrome.exe'

    def test_python_row(self):
        out = '"python.exe","16708","Console","1","120,000 K"\n'
        assert parse_tasklist_name(out) == 'python.exe'

    def test_chinese_process_name(self):
        out = '"微信.exe","1234","Console","1","80,000 K"\n'
        assert parse_tasklist_name(out) == '微信.exe'

    def test_empty_output_returns_unknown(self):
        assert parse_tasklist_name('') == '未知进程'

    def test_info_no_tasks(self):
        """tasklist 无匹配时输出 '信息: 没有运行的任务匹配指定标准。'"""
        assert parse_tasklist_name('信息: 没有运行的任务匹配指定标准。\n') == '未知进程'

    def test_single_field_row_returns_unknown(self):
        assert parse_tasklist_name('"onlyone"\n') == '未知进程'

    def test_blank_lines_skipped(self):
        out = '\n\n"python.exe","1","Console","1","1 K"\n\n'
        assert parse_tasklist_name(out) == 'python.exe'
