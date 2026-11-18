"""关键链路真库证明的「环境缺失必须签字」闸（2026-10-17 审计 TEST-BE-B §3.1 / P1-3）。

问题
----
本仓多条 P0 链路的**唯一真库证明**都用 `pytest.skip` 处理「测试库不可达」。
这些 skip 长得像「环境缺失」，实际等价于「这条证据从没跑过」—— AGENTS 铁律 1
「证据先于断言」在这里被静默架空。本仓已经吃过这个亏：
`fastapi_app/tests/test_import_idempotency_constraints.py:301-303` 的原话是

    2026-11-03 实测：该 skip 掩盖了「真实 PG 幂等约束证明从未执行」，
    全量 62 条 skip 里它伪装成「环境缺失」。

同形写法在 7 个文件里仍未收口，且没有任何「关键用例不允许 skip」的门禁。
非提权 / `.env` 不可读 / PG 端口未开 —— 任一条件成立，这些链路全部变绿
（skip），全量数字仍是「全绿 + N skipped」，没人会去看 N 的构成。

做法（审计 §3.1 修法③）
--------------------
环境前提不满足时**默认 fail**，只有显式设 `ALLOW_MISSING_TEST_DB=1` 才 skip。
「让缺口必须有一个人签字」：确属本地环境缺失（无测试库的只读机器）时，
必须有人显式写下这个环境变量并在报告里注明，而不是让它悄悄算进 skipped。

为什么不设成「skip 数预算棘轮」
------------------------------
全量 skip 数在不同环境天然不同（有/无 prometheus、有/无在线 nginx），
一个全局预算会天天误报，最后一定被人放宽成废纸。精准到「这几条真库证明」
才有意义 —— 它们是 AGENTS §4「每条修复都要有当场跑出的证据」的落脚点。

注意本模块**只管测试库不可达**这类环境前提。以下两类刻意不用它：
  · 「工具链/凭据缺失」（`pg_dump` 不在 PATH、未配 `PG_SUPER_PASSWORD`）——
    本机生产机确实没有 `pg_dump` 在 PATH 上，改 fail 只会让本地全量永久红。
    另一半原因此前写错过（2026-11-18 评审 Med2 更正）：当时写「这两条在 CI 上会
    真跑」，但 CI **只装了 postgresql-client-18**（`pg_dump` 那条成立），
    workflow 里并没有 `PG_SUPER_PASSWORD` —— `test_restore_real_roundtrip.py`
    的超管分支在**本机和 CI 都不执行**。也就是说它是一个已知的真实缺口，
    不是「已由 CI 覆盖」。要收口得给 CI 补 `PG_SUPER_PASSWORD` 再把它接进闸门。
  · 「数据前置条件」（测试库已有历史数据，跳过以免误删）—— 那是保护措施，
    不是覆盖缺口。
"""
from __future__ import annotations

import os
from typing import NoReturn

#: 显式签字的环境变量。设成 `1` 才允许把「测试库不可达」降级为 skip。
ALLOW_ENV = 'ALLOW_MISSING_TEST_DB'


def allow_missing_test_db() -> bool:
    """是否已由人显式放行「测试库不可达」。

    **CI 里恒为 False**（2026-11-18 评审 Med3）：CI 的 test job 本来就带 postgres
    service，不需要这个出口；而一旦有人在 workflow 的 `env:` 里加一行
    `ALLOW_MISSING_TEST_DB: "1"`，13 道闸门会一起退回 skip，而守卫测试照样全绿
    （守卫用的是 `monkeypatch`，看不到 CI 的真实环境）。所以这里硬性关掉 ——
    缺口在 CI 上必须变成红色，不能靠一个环境变量全部消音。
    """
    if os.environ.get('GITHUB_ACTIONS', '').strip().lower() == 'true':
        return False
    return os.environ.get(ALLOW_ENV) == '1'


def require_test_db(reason: str) -> NoReturn:
    """测试库前提不满足：默认 fail，只有显式 `ALLOW_MISSING_TEST_DB=1` 才 skip。

    :param reason: 具体到什么不可用（端口/URL/异常类型），会进失败消息。

    这个函数**总是终止当前用例**（raise / skip 都是异常），所以返回类型是 NoReturn。
    """
    import pytest

    if allow_missing_test_db():
        pytest.skip(f'{reason}（已由 {ALLOW_ENV}=1 显式放行）')
    pytest.fail(
        f'{reason}\n'
        '  这是关键链路的**唯一真库证明**：默认失败，是为了让「证据没跑」可见，\n'
        '  而不是让它悄悄算进 skipped（2026-10-17 审计 §3.1 / P1-3）。\n'
        f'  确属本地环境缺失时，显式设 {ALLOW_ENV}=1 再跑，并在报告里注明。',
        pytrace=False,
    )
