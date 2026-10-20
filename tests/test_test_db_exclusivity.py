"""测试库独占护栏回归（审计 Z09-R5）

本会话的会话夹具会对测试库执行 DROP SCHEMA public CASCADE 整库重置。
两个 pytest 实例并跑同一测试库必然互撞出假红，AGENTS.md §4 的"全量 pytest
必须独占单实例"此前只是文档约束；现由 tests/conftest.py 的咨询锁做机器护栏。

护栏本身在测试进程内无法直接验证（子进程要抢的正是本进程持有的锁），
故这里起一个**子进程 pytest**去撞锁：子进程必须在动手碰 schema 之前就被
拒掉（退出码 2），从而证明它不会与本会话互相破坏数据。
"""
import os
import subprocess
import sys

import pytest

MARK = pytest.mark.integration

# 子进程要撞的锁在 tests/conftest.py；本文件同目录，故从仓库根跑 pytest
# 才能加载到那棵树的 conftest。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 子进程只需跑到 conftest 的会话夹具就会被拒，选一个最轻的用例文件即可。
_CHILD_TARGET = "tests/test_purchase_supplier_service.py"


@MARK
class TestTestDbExclusivity:

    @pytest.mark.asyncio
    async def test_second_instance_is_refused_before_touching_schema(self, test_engine):
        """第二个 pytest 实例必须被独占锁拒掉（退出码 2），且未跑任何用例。

        断言只依赖 ASCII 片段：Windows 控制台按 GBK 解码子进程输出，中文
        断言会因编码而假红。
        """
        env = dict(os.environ)
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", _CHILD_TARGET, "-q", "-p", "no:cacheprovider"],
            cwd=_PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
        combined = (proc.stdout or "") + (proc.stderr or "")

        assert proc.returncode == 2, (
            f"第二个实例应以退出码 2 被独占锁拒掉，实际 {proc.returncode}:\n{combined[-800:]}"
        )
        # 消息里点名了危险动作，便于人判断"为什么被拒"
        assert "DROP SCHEMA public CASCADE" in combined, f"拒跑消息应说明危险动作:\n{combined[-800:]}"
        # 子进程必须在动手之前就退出，一个用例都不该跑
        assert "no tests ran" in combined, f"子进程应一个用例都不跑:\n{combined[-800:]}"
