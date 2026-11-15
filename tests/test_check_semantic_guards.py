"""scripts/check_semantic_guards.py 回归测试

覆盖三类语义门禁的**正例与反例**（只测正例的门禁，等于没测：
把判定写死成「永远命中」也能过），外加两个最容易腐烂的边界：

- 豁免清单缺 reason 必须**无效**（否则「加一行空条目」就是关闭门禁的开关）；
- AST 解析失败 / 扫描面为空必须退出 2（解析失败 ≠ 无违规，这是假绿的主要来源）。

为什么大部分用例走**子进程**而不是 import 函数：脚本在 import 时会把 sys.stdout
换成 UTF-8 wrapper（Windows 控制台是 GBK，不换会乱码），在 pytest 进程里 import
会污染后续所有用例的捕获输出。子进程同时顺带证明了「命令行真的接上了判定」。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "check_semantic_guards.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def _payload(proc: subprocess.CompletedProcess[str]) -> dict:
    """解析 --json 输出（JSON 一定在 stdout 起始处）。"""
    return json.loads(proc.stdout.strip().splitlines()[0])


def _write(dirpath: Path, name: str, content: str) -> Path:
    path = dirpath / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# authz_missing：写接口缺 RBAC
# ---------------------------------------------------------------------------

_NO_AUTHZ = """
from fastapi import APIRouter, Depends

router = APIRouter()


@router.post('/widgets')
async def create_widget(db=Depends(get_async_db)):
    return db
"""

_WITH_AUTHZ = """
from fastapi import APIRouter, Depends

router = APIRouter()


@router.post('/widgets')
async def create_widget(
    db=Depends(get_async_db),
    user=Depends(require_permission('widget_manage')),
):
    return db
"""


def test_authz_missing_is_flagged(tmp_path):
    _write(tmp_path, "endpoints.py", _NO_AUTHZ)

    proc = _run("--json", str(tmp_path))

    data = _payload(proc)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert len(data["authz_missing"]) == 1
    assert data["authz_missing"][0]["function"] == "create_widget"


def test_authz_dependency_is_not_flagged(tmp_path):
    _write(tmp_path, "endpoints.py", _WITH_AUTHZ)

    proc = _run("--json", str(tmp_path))

    data = _payload(proc)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert data["authz_missing"] == []


def test_authz_accepts_require_family_and_write_scope(tmp_path):
    """按前缀认整族 require_*（backup 的 require_backup_permission 是一例），
    并认得 `Depends(resolve_production_write_scope)` 这种直接引用函数对象的写法。"""
    _write(
        tmp_path,
        "endpoints.py",
        """
from fastapi import APIRouter, Depends

router = APIRouter()


@router.delete('/backups/{name}')
async def drop_backup(name: str, user=Depends(require_backup_permission('drop'))):
    return name


@router.put('/records/{rid}')
async def update_record(rid: int, scope=Depends(resolve_production_write_scope)):
    return rid
""",
    )

    data = _payload(_run("--json", str(tmp_path)))
    assert data["authz_missing"] == []


def test_upload_magic_validator_does_not_count_as_authz(tmp_path):
    """`require_upload_magic` 是文件头校验，不是授权；按前缀一刀切会放过真缺口。"""
    _write(
        tmp_path,
        "endpoints.py",
        """
from fastapi import APIRouter, Depends

router = APIRouter()


@router.post('/upload')
async def upload(file, db=Depends(get_async_db)):
    require_upload_magic(b'PK', ('zip',), filename='a.zip')
    return file
""",
    )

    data = _payload(_run("--json", str(tmp_path)))
    assert len(data["authz_missing"]) == 1


# ---------------------------------------------------------------------------
# lock_order：StockIn 先、Product 后
# ---------------------------------------------------------------------------

_LOCK_REVERSED = """
async def touch(db, stockin_id):
    result = await db.execute(
        select(StockIn).where(StockIn.id == stockin_id).with_for_update()
    )
    product = await get_product_for_update(db, result.product_id)
    return product
"""

_LOCK_CORRECT = """
async def touch(db, stockin_id):
    product = await get_product_for_update(db, stockin_id)
    result = await db.execute(
        select(StockIn).where(StockIn.id == stockin_id).with_for_update()
    )
    return product
"""


def test_lock_order_reversed_is_flagged(tmp_path):
    _write(tmp_path, "service.py", _LOCK_REVERSED)

    proc = _run("--json", str(tmp_path))

    data = _payload(proc)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert len(data["lock_order"]) == 1
    assert "StockIn" in data["lock_order"][0]["detail"]


def test_lock_order_correct_is_not_flagged(tmp_path):
    """Product → StockIn 是本仓统一约定，不能报。"""
    _write(tmp_path, "service.py", _LOCK_CORRECT)

    data = _payload(_run("--json", str(tmp_path)))
    assert data["lock_order"] == []


def test_lock_order_inline_exemption(tmp_path):
    """行内 `# lock-order-ok: <理由>` 可豁免；只写标记不写理由仍算违规。"""
    _write(
        tmp_path,
        "ok.py",
        _LOCK_REVERSED.replace(
            "with_for_update()", "with_for_update()  # lock-order-ok: 该路径只按 stockin 加锁"
        ),
    )
    assert _payload(_run("--json", str(tmp_path)))["lock_order"] == []

    _write(tmp_path, "bad.py", _LOCK_REVERSED.replace("with_for_update()", "with_for_update()  # lock-order-ok:"))
    (tmp_path / "ok.py").unlink()
    assert len(_payload(_run("--json", str(tmp_path)))["lock_order"]) == 1


# ---------------------------------------------------------------------------
# idempotency_missing：POST 建单无幂等
# ---------------------------------------------------------------------------

_NO_IDEMPOTENCY = """
from fastapi import APIRouter, Depends

router = APIRouter()


@router.post('/orders/create')
async def create_order(data, user=Depends(require_permission('order_manage'))):
    return data
"""

_WITH_IDEMPOTENCY = """
from fastapi import APIRouter, Depends, Header

router = APIRouter()


@router.post('/orders/create')
async def create_order(
    data,
    user=Depends(require_permission('order_manage')),
    idempotency_key: str | None = Header(None, alias='Idempotency-Key'),
):
    return data
"""


def test_idempotency_missing_is_flagged(tmp_path):
    _write(tmp_path, "endpoints.py", _NO_IDEMPOTENCY)

    proc = _run("--json", str(tmp_path))

    data = _payload(proc)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert len(data["idempotency_missing"]) == 1
    assert data["idempotency_missing"][0]["function"] == "create_order"


def test_idempotency_header_is_not_flagged(tmp_path):
    _write(tmp_path, "endpoints.py", _WITH_IDEMPOTENCY)

    data = _payload(_run("--json", str(tmp_path)))
    assert data["idempotency_missing"] == []


def test_idempotency_body_header_read_counts(tmp_path):
    """不通过签名参数、而在函数体里读请求头也算（两种写法本仓都存在）。"""
    _write(
        tmp_path,
        "endpoints.py",
        """
from fastapi import APIRouter, Request

router = APIRouter()


@router.post('/batch/import')
async def batch_import(request: Request):
    key = request.headers.get('Idempotency-Key')
    return key
""",
    )

    data = _payload(_run("--json", str(tmp_path)))
    assert data["idempotency_missing"] == []


def test_non_create_post_path_is_ignored(tmp_path):
    """未命中建单语义词的 POST（如改状态）不在本规则范围内。"""
    _write(
        tmp_path,
        "endpoints.py",
        """
from fastapi import APIRouter, Depends

router = APIRouter()


@router.post('/widgets/{wid}/toggle')
async def toggle_widget(wid: int, user=Depends(require_permission('widget_manage'))):
    return wid
""",
    )

    data = _payload(_run("--json", str(tmp_path)))
    assert data["total"] == 0


# ---------------------------------------------------------------------------
# 豁免清单
# ---------------------------------------------------------------------------


def _allowlist(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "allow.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_allowlist_exempts_with_reason(tmp_path):
    probe = tmp_path / "probe"
    _write(probe, "endpoints.py", _NO_AUTHZ)
    allow = _allowlist(
        tmp_path,
        """
exemptions:
  - file: endpoints.py
    function: create_widget
    rule: authz_missing
    reason: 内部调试接口，权限由上游网关判定
""",
    )

    proc = _run("--json", f"--allowlist={allow}", str(probe))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _payload(proc)["total"] == 0


def test_allowlist_without_reason_is_invalid(tmp_path):
    """缺 reason 的豁免不生效：违规照常上报，并在 stderr 告警。"""
    probe = tmp_path / "probe"
    _write(probe, "endpoints.py", _NO_AUTHZ)
    allow = _allowlist(
        tmp_path,
        """
exemptions:
  - file: endpoints.py
    function: create_widget
    rule: authz_missing
""",
    )

    proc = _run("--json", f"--allowlist={allow}", str(probe))

    data = _payload(proc)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert len(data["authz_missing"]) == 1, "缺 reason 的豁免不得生效"
    assert "缺 reason" in proc.stderr


# ---------------------------------------------------------------------------
# 退出码 2：解析失败 / 扫描面为空
# ---------------------------------------------------------------------------


def test_parse_error_exits_2(tmp_path):
    _write(tmp_path, "broken.py", "def broken(:\n    pass\n")

    proc = _run("--json", str(tmp_path))

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert _payload(proc)["parse_errors"] == 1


def test_empty_scan_surface_exits_2(tmp_path):
    """路径写错时「0 处违规」毫无意义，必须判 2。"""
    proc = _run("--json", str(tmp_path / "does_not_exist"))

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert _payload(proc)["scanned"] == 0


# ---------------------------------------------------------------------------
# 接线路由前缀：只看装饰器字面量会漏掉 POST /orders/create
# ---------------------------------------------------------------------------


def test_router_prefixes_are_resolved():
    """`order.py` 的 `@router.post('/create')` 实际路径是 /orders/create。

    前缀配在 router.py 的 include_router(prefix=...) 里；取不到前缀，
    最该被看住的下单入口恰好不含 `orders` 字样，门禁会安静地漏掉它。

    走子进程而不是 import：该模块在 import 时把 sys.stdout 换成 UTF-8 wrapper，
    在 pytest 进程里做这件事会在 wrapper 被回收时关掉捕获缓冲，连累其它用例
    报 "I/O operation on closed file"。
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, scripts.check_semantic_guards as sg;"
            "print(json.dumps(sg._module_prefix_map()))",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert proc.returncode == 0, proc.stderr
    prefixes = json.loads(proc.stdout)

    assert prefixes.get("order") == "/orders"
    assert prefixes.get("staging_order") == "/staging-orders"
    assert prefixes.get("batch") == "/batch"
    assert prefixes.get("ocr_import") == "/ocr-import"
    assert prefixes.get("purchase_center") == "/purchase-center"


# ---------------------------------------------------------------------------
# 接线：门禁在 quality_gate 里注册且基线有该键
# ---------------------------------------------------------------------------


def test_gate_registered_in_quality_gate():
    import scripts.quality_gate as q

    gate = next((g for g in q.GATES if g.key == "semantic_guards"), None)
    assert gate is not None, "semantic_guards 未接入 quality_gate.GATES"
    assert gate.mode == q.MODE_JSON
    assert gate.count_key == "total"
    assert gate.accepts_paths, "--self-test 依赖 --probe-dir 覆盖扫描面"

    counts = q.load_baseline()
    assert counts is not None and "semantic_guards" in counts, \
        "基线缺少 semantic_guards 键，门禁会判 ERROR"


def test_baseline_matches_measured_total():
    """基线数字必须等于实测总数：否则要么恒 REGRESS，要么悄悄变松。"""
    proc = _run("--json")
    data = _payload(proc)

    import scripts.quality_gate as q

    baseline = q.load_baseline()
    assert baseline is not None
    assert data["total"] == baseline["semantic_guards"], (
        f"实测 {data['total']} 处 != 基线 {baseline['semantic_guards']} 处"
        "（修好了就下调基线，新增了就修代码）"
    )
    assert data["total"] == (
        len(data["authz_missing"])
        + len(data["lock_order"])
        + len(data["idempotency_missing"])
    ), "total 必须等于三项之和"


def test_bare_except_json_reports_exemptions():
    """任务一的可见性契约：已豁免数量必须能从 --json 读到，且数值自洽。"""
    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "check_bare_except.py"), "--json"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    data = json.loads(proc.stdout.strip().splitlines()[0])

    assert {"scanned", "raw_total", "exempted", "total"} <= set(data)
    assert data["total"] == len(data["violations"]), "total 仍是未申报数"
    assert data["exempted"] == data["raw_total"] - data["total"]
    assert data["scanned"] > 0
    assert data["raw_total"] >= data["total"]
