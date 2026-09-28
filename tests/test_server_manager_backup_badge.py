"""server_manager 备份徽章接入的静态断言(无 GUI 测试基建,以文本锁定)。"""
from __future__ import annotations

import ast
from pathlib import Path

# 2026-09-28 包化:实现已拆到 server_manager/ 包,本文件按"整包拼接"取文本,
# 这样 task 2-6 继续把代码拆去 service_ops/windows_ops/... 时无需再改本文件。
PKG = Path(__file__).resolve().parent.parent / "server_manager"
TEXT = "\n".join(p.read_text(encoding="utf-8") for p in sorted(PKG.glob("*.py")))

# ★ 修正(T7):凡用 ``TEXT.index(锚点)`` 切片的断言,在实现搬家后会命中同名的瘦转发体
#   (或按 sorted(glob) 的字典序落到别的模块),切片指向错误位置甚至**区间为空**。
#   T7 把采集/渲染搬进 ``server_manager/hosting_view.py``(HostingViewMixin) 后统一改为
#   ``_func_src(模块, 函数名)`` 按 AST 精确定位**目标模块内**的函数体,不再依赖任何
#   模块顺序/摆放假设。
HOSTING_VIEW = "hosting_view.py"


def _func_src(rel_path: str, name: str) -> str:
    """按 AST 取指定模块内某函数/方法的源码段(含缩进),不依赖 TEXT.index 顺序。"""
    src = (PKG / rel_path).read_text(encoding="utf-8")
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"{rel_path} 内未找到 {name}")


def test_backup_badge_widget_exists() -> None:
    assert "hosting_backup_badge = StatusBadge(" in TEXT


def test_backup_badge_is_rendered() -> None:
    # D 步把渲染函数内的局部闭包 ``_detail`` 方法化为 ``self._set_badge``
    # (函数长度门禁拆分),调用点随之改名,断言跟随。
    assert "_set_badge(self.hosting_backup_badge" in TEXT
    assert "data.get('backup')" in TEXT


def test_hosting_collects_backup_block() -> None:
    """采集阶段必须去取 /api/health 的 backup 块(渲染阶段不做 IO)。"""
    assert "data['backup'] = {}" in TEXT
    assert "payload.get('backup')" in TEXT


def test_local_probe_bypasses_proxy() -> None:
    """本机探针必须绕开系统代理——prod_runner 曾因代理转发 127.0.0.1 导致误判重启。"""
    assert "ProxyHandler({})" in TEXT
    assert "_HTTP_DIRECT.open(" in TEXT


def test_collect_does_not_fetch_with_plain_urlopen() -> None:
    """采集路径不得用裸 urlopen(会被系统代理截走);应走 _HTTP_DIRECT。"""
    seg = _func_src(HOSTING_VIEW, "_collect_hosting_data")
    assert "_HTTP_DIRECT.open(" in seg
    assert "urllib.request.urlopen(" not in seg


def test_every_early_return_updates_backup_badge() -> None:
    """回归锁:调度器里每个提前 return 必须经由「放弃型」助手,且该助手确实置灰备份徽章。

    备份取值来自每轮采集,不经状态文件;任何提前 return 漏掉它,都会让旧值滞留
    ——2026-09-28 用户实测到的假健康(服务全停仍显示绿色「正常(8.5h)」)就是这么来的。
    该缺陷在拆分前的单函数里出现过四次(collect_error / 未运行 / 启动窗口 / 状态不可信),
    故此处扫全部分支,而不是逐条列举。

    ★ 重锚(D 步,函数长度门禁):拆分前 ``_apply_hosting_data`` 是一个 155 行的单函数,
    本锁扫它**函数体内**每个 ``return`` 前 20 行是否出现 ``hosting_backup_badge``。D 步按
    「放弃理由」把它拆成「调度器 + 放弃型助手」后,备份徽章的置灰搬进了助手体内,调度器里
    只剩下 ``self._apply_xxx(data); return`` —— 旧形式(扫调度器体内文本)必然失效,故重锚。
    新形式要求调度器里每个 ``return`` 之前**紧邻调用**了一个放弃型助手
    (``_apply_collect_error`` / ``_apply_services_stopped`` / ``_apply_status_untrusted``),
    且该助手**函数体**内含有 ``hosting_backup_badge`` 置灰语句。

    ★ 窗口从 20 行收窄到 3 行(D 步评审证伪):初版沿用了拆分前的 20 行窗口,而调度器总共
    才 ~35 行 —— 于是在调度器**尾部**插入一条裸 ``return`` 时,它前面 20 行里必然含有前面
    几个 ``self._apply_xxx(...)`` 调用,``any(...)`` 恒真 ⇒ 该裸 return **不会被发现**
    (评审实测:注入后本条仍 PASSED)。也就是说初版**没有**兑现"加了绕过置灰的出口仍会红"
    的承诺。收窄到 3 行后,裸 return 会红(其紧邻上文是 ``_apply_running_status`` 之类,
    不在放弃型助手里),而「调用与 return 之间夹一两行」仍被容忍 —— 语义这才真的只紧不松。
    验证方式见同目录报告:注入裸 return → 本条红;还原 → 绿。

    ★ 更早的修正(T7):旧版用 ``TEXT[TEXT.index(apply):TEXT.index(collect)]`` —— ``apply``
    在 ``collect`` **之后**,区间恒为空、``misses`` 恒为空,本条长期是**空转锁**。T7 改为
    对目标模块 ``hosting_view.py`` 按 AST 取**函数体**,并加防空转断言。
    """
    # 4 个「放弃理由」分支拆出的三个提前 return 助手(collect_error 分支已是第一个 return)。
    abandonment_helpers = (
        "_apply_collect_error",
        "_apply_services_stopped",
        "_apply_status_untrusted",
    )
    # 每个放弃型助手自身必须真的置灰备份徽章,否则「经过助手」也只是形式。
    for helper in abandonment_helpers:
        body = _func_src(HOSTING_VIEW, helper)
        assert "hosting_backup_badge" in body, (
            f"放弃型助手 {helper}() 体内未置灰备份徽章 → 该分支会滞留旧值成假信号"
        )

    dispatcher = _func_src(HOSTING_VIEW, "_apply_hosting_data")
    lines = dispatcher.splitlines()
    # 防空转:切片必须真的落在调度器函数体上,且确实取到了提前 return(否则本锁名存实亡)
    assert lines and lines[0].strip().startswith("def _apply_hosting_data("), "AST 切片未取到 _apply_hosting_data 函数体"
    early_returns = [i for i, line in enumerate(lines) if line.strip() == "return"]
    assert early_returns, "调度器函数体内未取到任何提前 return,本条会空转"
    # 窗口只容忍「调用与 return 之间夹一两行」;不能再宽 —— 调度器整体才 ~35 行,
    # 宽窗口会让尾部任意裸 return 都落在前面某个助手调用的 20 行内(评审已证伪)。
    WINDOW = 3
    misses = []
    for i in early_returns:
        window = "\n".join(lines[max(0, i - WINDOW):i])
        if not any(f"self.{helper}(" in window for helper in abandonment_helpers):
            misses.append(i)
    assert not misses, (
        f"_apply_hosting_data 有 {len(misses)} 处提前 return 未经放弃型助手 "
        "(备份徽章可能滞留旧值 → 旧值滞留成假信号)"
    )
