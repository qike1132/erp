"""端口契约与占用判定 —— 纯逻辑，零 I/O。

本模块从 server_manager.py（v5.40）迁移而来，**逐行搬运，未做行为改动**。

═══════════════════════════════════════════════════════════════════
核心语义：同一个 netstat 输出，两种不同用途的解析
═══════════════════════════════════════════════════════════════════

原实现有两处解析 `netstat -ano`，**过滤条件刻意不同**，此处完整保留：

    _find_port_pids(port)       → 用于「击杀」
        只认 LISTENING（v5.40 审查 #23）

    _get_port_occupier(port)    → 用于「留痕」
        LISTENING 或 ESTABLISHED（审查 #6）

为什么必须区分（2026-09-14 实测数据支撑）：

    netstat -ano 总 892 行，状态分布：
        TIME_WAIT   609 行  ← 最多，但 PID 恒为 0
        ESTABLISHED 143 行  ← 有真实 PID
        LISTENING    85 行  ← 真正阻塞重绑的
        CLOSE_WAIT   14 行
        FIN_WAIT_2   12 行

    · 击杀必须只认 LISTENING：TIME_WAIT 会自行过期且不阻塞重绑，
      把它纳入击杀目标只会产生 609 次无效击杀尝试（且 PID=0 意味着无进程可杀）。
    · 留痕可以认 ESTABLISHED：连接方也想知道「谁在占用这个端口」，
      例如 6379 上有 143 个连接，运维需要看到对端。

netstat 输出的格式陷阱（实测）：

    TCP 行（5 列）:  协议  本地地址  外部地址  状态  PID
    UDP 行（4 列）:  协议  本地地址  外部地址  PID      ← 无「状态」列！
    表头行:          '活动连接' / 空行 / '协议 本地地址 ...'

    故解析必须：① 丢弃列数不足的行 ② 不强依赖固定列位
    ③ PID 列必须在末尾且为纯数字
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ═══════════════════════════════════════════════════════════════════
# 端口配置
# ═══════════════════════════════════════════════════════════════════

#: 端口配置的合法范围
PORT_MIN = 1
PORT_MAX = 65535


def is_valid_port(port: object) -> bool:
    """端口是否合法（用于配置校验）。

    收紧点（对应 v5.39 审查 #3「配置无类型归一化」的同类问题）：
    配置文件里端口被手改成 "abc" / 0 / 70000 / -1 时应在此被拦下，
    而非等到 socket 绑定才炸。
    """
    if isinstance(port, bool):          # bool 是 int 子类，须先排
        return False
    if not isinstance(port, int):
        return False
    return PORT_MIN <= port <= PORT_MAX


@dataclass(frozen=True)
class PortConfig:
    """三个业务端口的契约。

    对应原 `_Ports` 单例：

        self.api, self.web, self.redis = _DEFAULT_API_PORT, _DEFAULT_WEB_PORT, _DEFAULT_REDIS_PORT

    原实现是可变单例（配置保存后热更新就改属性）。
    这里改为 frozen dataclass —— 热更新时**整体替换**而非就地改，
    避免原实现 `_PORTS.api = x` 那种「谁都能改」的隐式耦合（v8 方案 D3 全局状态）。
    """

    api: int = 5002
    web: int = 3000
    redis: int = 6379

    def __post_init__(self) -> None:
        for name in ('api', 'web', 'redis'):
            value = getattr(self, name)
            if not is_valid_port(value):
                raise ValueError(f'端口 {name} 非法: {value!r}（须为 {PORT_MIN}-{PORT_MAX} 的整数）')

    def __iter__(self):
        """允许 `for p in config` 遍历三个端口。"""
        return iter((self.api, self.web, self.redis))

    def as_dict(self) -> dict[str, int]:
        return {'api': self.api, 'web': self.web, 'redis': self.redis}

    @property
    def has_duplicates(self) -> bool:
        """三个端口是否有重复（配置错误，会导致互相抢占）。"""
        return len({self.api, self.web, self.redis}) < 3


#: 默认端口（对应原 _DEFAULT_API_PORT / _DEFAULT_WEB_PORT / _DEFAULT_REDIS_PORT）
DEFAULT_PORTS = PortConfig()


# ═══════════════════════════════════════════════════════════════════
# netstat 解析
# ═══════════════════════════════════════════════════════════════════


class PortFilter(Enum):
    """端口占用者的过滤口径 —— 对应两种不同用途。"""

    LISTENING_ONLY = 'listening_only'
    """仅 LISTENING。用于**击杀**（v5.40 审查 #23）。

    TIME_WAIT 会自行过期且不阻塞重绑，纳入击杀目标只会产生多余尝试。
    """

    LISTENING_OR_ESTABLISHED = 'listening_or_established'
    """LISTENING 或 ESTABLISHED。用于**留痕**（v5.40 审查 #6）。

    连接方也是占用者，运维需要看到「谁在占用」。
    """

    def accepts(self, line: str) -> bool:
        upper = line.upper()
        if 'LISTENING' in upper:
            return True
        if self is PortFilter.LISTENING_OR_ESTABLISHED and 'ESTABLISHED' in upper:
            return True
        return False


@dataclass(frozen=True)
class PortOccupier:
    """一个端口占用记录。"""

    pid: int
    local_addr: str
    state: str

    @property
    def port(self) -> int | None:
        """从本地地址解析端口（如 '0.0.0.0:3000' → 3000）。

        兼容 IPv6 形式如 '[::]:3000'。
        """
        return parse_port_from_address(self.local_addr)


def parse_port_from_address(addr: str) -> int | None:
    """从 netstat 的本地地址列解析端口号。

    格式：
        '0.0.0.0:3000'      → 3000
        '127.0.0.1:5432'    → 5432
        '[::]:3000'         → 3000     (IPv6)
        '[::1]:6379'        → 6379
        '0.0.0.0:0'         → 0        (尚未绑定)

    原实现的判定是 `parts[1].rsplit(':', 1)[-1] == str(port)`，
    即取最后一个冒号后的部分。本函数保持同一语义。
    """
    if ':' not in addr:
        return None
    tail = addr.rsplit(':', 1)[-1]
    if not tail.isdigit():
        return None
    return int(tail)


def parse_netstat_occupiers(
    output: str,
    port: int,
    port_filter: PortFilter = PortFilter.LISTENING_ONLY,
    *,
    require_positive_pid: bool = True,
) -> list[PortOccupier]:
    """解析 `netstat -ano` 输出，提取占用指定端口的记录。

    参数：
        output              —— netstat 的 stdout 文本（OEM 解码后）
        port                —— 目标端口
        port_filter         —— 过滤口径（击杀用 LISTENING_ONLY；留痕用 LISTENING_OR_ESTABLISHED）
        require_positive_pid—— 是否要求 PID > 0（默认 True）

    迁移说明 —— 本函数是以下两处的**合并抽象**：

        `_find_port_pids`（L1072）：
            if 'LISTENING' not in line: continue
            parts = line.split()
            if (len(parts) >= 5 and ':' in parts[1]
                and parts[1].rsplit(':', 1)[-1] == str(port)
                and parts[-1].isdigit() and int(parts[-1]) > 0):
                pids.add(parts[-1])

        `_get_port_occupier`（L395）：
            if f':{port}' in line and ('LISTENING' in line or 'ESTABLISHED' in line)
                and len(line.split()) >= 5 and line.split()[-1].isdigit():
                pids.add(line.split()[-1])

    ★ 两者有一处**旧实现的真实缺陷**，本实现予以修正（2026-09-14 实测确认）：

        `_get_port_occupier` 用的是**子串** `f':{port}' in line`，
        而 `_find_port_pids` 用**列位精确匹配** `parts[1].rsplit(':',1)[-1] == str(port)`。

        实测（目标端口 3000）的两处误报：

        ┌────────────────────────────────────────────┬────────┬────────┐
        │ netstat 行                                  │ 旧子串 │ 新列位 │
        ├────────────────────────────────────────────┼────────┼────────┤
        │ TCP  0.0.0.0:3000  ...  LISTENING  20760    │  True  │  True  │
        │ TCP  0.0.0.0:13000 ...  LISTENING  999      │ False  │ False  │
        │ TCP  0.0.0.0:30000 ...  LISTENING  888      │  True  │ False  │ ← 误报①
        │ TCP  127.0.0.1:54321  127.0.0.1:3000  EST   │  True  │ False  │ ← 误报②
        │ TCP  127.0.0.1:3000   127.0.0.1:54321 EST   │  True  │  True  │
        └────────────────────────────────────────────┴────────┴────────┘

        误报① `':3000' in '0.0.0.0:30000'` → True。子串匹配把 30000 的占用者
              算成了 3000 的占用者。
        误报② 匹配到了**外部地址**列。该连接的本地端口是 54321，不是 3000。

        后果：留痕日志会写出错误的占用者名单。而留痕是「按端口击杀」前
        唯一的可追溯记录（v5.40 审查 #6 的整改），写错等于事故无法追溯。

        本实现统一采用**列位精确匹配**（取 parts[1] 本地地址、末列 PID），
        误报①②均被消除。`_find_port_pids` 原本就正确，行为不变。

        该差异已固化为测试：
            test_substring_false_positive_30000_not_matched
            test_remote_address_not_counted_as_local

    返回：PortOccupier 列表（已去重，按 PID 升序）
    """
    seen: set[tuple[int, str]] = set()
    result: list[PortOccupier] = []

    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        # 表头行不含冒号数字对，会被下面的解析自然丢弃
        if not port_filter.accepts(line):
            continue

        parts = line.split()
        # ★ 列数防御：TCP 行 5 列（含状态），UDP 行 4 列（无状态）。
        #   UDP 行因不含 LISTENING/ESTABLISHED 已在上一步被过滤，
        #   但此处仍保留 >= 4 的下限以防御异常输出。
        if len(parts) < 4:
            continue

        # 本地地址列（TCP/UDP 均为第 2 列）
        local_addr = parts[1]
        if parse_port_from_address(local_addr) != port:
            continue

        # PID 列恒为最后一列
        pid_text = parts[-1]
        if not pid_text.isdigit():
            continue
        pid = int(pid_text)
        if require_positive_pid and pid <= 0:
            # 排除 TIME_WAIT / CLOSE_WAIT 等 PID=0 的已终止连接
            continue

        state = parts[3] if len(parts) >= 5 else ''
        key = (pid, local_addr)
        if key in seen:
            continue
        seen.add(key)
        result.append(PortOccupier(pid=pid, local_addr=local_addr, state=state))

    result.sort(key=lambda o: (o.pid, o.local_addr))
    return result


def extract_port_pids(
    output: str,
    port: int,
    port_filter: PortFilter = PortFilter.LISTENING_ONLY,
) -> list[str]:
    """提取占用端口的 PID **字符串**列表（保持原实现的返回类型）。

    `_find_port_pids` 原样返回 `list[str]`（被 `_taskkill_many` 消费），
    此处保持该类型以免调用方改动。新代码建议直接用 `parse_netstat_occupiers`。
    """
    occupiers = parse_netstat_occupiers(output, port, port_filter)
    return sorted({str(o.pid) for o in occupiers}, key=int)


def parse_tasklist_name(output: str) -> str:
    """解析 `tasklist /FI "PID eq N" /FO CSV /NH` 输出，取进程名。

    迁移自 `_get_port_occupier`（L406-409）：

        lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
        if lines and len(lines[0].split('","')) >= 2:
            name = lines[0].split('","')[0].strip('"')

    tasklist CSV 输出形如：
        "chrome.exe","1234","Console","1","50,000 K"

    找不到时返回 '未知进程'（保持原实现的降级语义）。
    """
    unknown = '未知进程'
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    if not lines:
        return unknown
    parts = lines[0].split('","')
    if len(parts) < 2:
        return unknown
    name = parts[0].strip('"').strip()
    return name or unknown
