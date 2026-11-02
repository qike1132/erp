"""XLSX 统一资源预算（M5，2026-10-25 上线前检查）回归测试。

行为锁定：
- ZIP 层：正常工作簿放行；成员数/单成员/总解压/压缩比超限一律拒；
- 工作簿层：行列超限**显式拒绝**（iter_rows 的 max_row 是硬裁剪，静默丢行
  会无声吞数据——多读一行的探测行必须被调用方判定）；
- 时间层：超时转 XlsxBudgetError（链路转 400/导入失败）；
- 单元格图片提取：预算未通过返回空 dict 不抛（图片缺失不阻断导入）；
- Polars 链：parse_excel_file_async 对炸弹/超限文件返回友好失败。
"""
from __future__ import annotations

import io
import zipfile

import pytest

from fastapi_app.services import batch_import_parser, xlsx_budget
from fastapi_app.services.xlsx_budget import (
    MAX_COMPRESSION_RATIO,
    XlsxBudgetError,
    assert_rows_within_budget,
    assert_zip_budget,
    run_parse_with_timeout,
)


def _make_xlsx(rows: int = 3, cols: int = 3) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in range(rows):
        ws.append([f'c{r}-{c}' for c in range(cols)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _zip_with(members: dict[str, bytes], compress_type: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compress_type) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# ZIP 层
# ---------------------------------------------------------------------------

def test_normal_workbook_passes():
    assert_zip_budget(_make_xlsx())


def test_corrupt_zip_raises_bad_zipfile():
    """非 zip 内容维持 BadZipFile 口径（各链路已有该异常 →「文件无法解析」）。"""
    with pytest.raises(zipfile.BadZipFile):
        assert_zip_budget(b'not a zip at all' * 10)


def test_high_compression_ratio_is_rejected():
    """零流 deflate 压缩比 >>100:1 —— zip 炸弹指纹必须在解压前拦下。"""
    bomb = _zip_with({'xl/worksheets/sheet1.xml': b'\x00' * (8 * 1024 * 1024)})
    with pytest.raises(XlsxBudgetError, match='压缩比'):
        assert_zip_budget(bomb)
    assert MAX_COMPRESSION_RATIO >= 100


def test_too_many_zip_members_rejected():
    members = {f'xl/media/img{i}.png': b'x' for i in range(501)}
    with pytest.raises(XlsxBudgetError, match='成员数'):
        assert_zip_budget(_zip_with(members, zipfile.ZIP_STORED))


def test_total_uncompressed_budget(monkeypatch):
    monkeypatch.setattr(xlsx_budget, 'MAX_TOTAL_UNCOMPRESSED_BYTES', 1024)
    with pytest.raises(XlsxBudgetError, match='总量'):
        assert_zip_budget(_make_xlsx())  # 正常 xlsx 解压总量 > 1KB


def test_single_member_budget(monkeypatch):
    monkeypatch.setattr(xlsx_budget, 'MAX_MEMBER_UNCOMPRESSED_BYTES', 512)
    with pytest.raises(XlsxBudgetError, match='单个成员'):
        assert_zip_budget(_make_xlsx())


# ---------------------------------------------------------------------------
# ZIP 层：物理膨胀试探（RJ-1，2026-11-02 实证修复）
# ---------------------------------------------------------------------------

def _make_underdeclared_bomb(
    member: str = 'bomb.bin',
    nominal_out: int = 32 * 1024 * 1024,
    declared: int = 64 * 1024,
    crc_consistent: bool = False,
) -> bytes:
    """构造「低报 file_size 的高膨胀」zip 成员——头部三道声明判定全部失明。

    手法与真实攻击一致：物理数据是解压输出 ~nominal_out 的高膨胀 raw deflate
    流（STORED 写入避免 zipfile 二次压缩），再把 local/central 头 patch 成
    DEFLATED + 谎报 file_size。声明比值 declared/压缩流大小 ≈ 2:1（远低于
    100:1 闸门）、单成员 64KiB（远低于 64MiB 闸门）——只有物理试探能拦。

    crc_consistent=True 时把头部 CRC 改成「按声明值截断的输出前缀」的
    CRC32——推送前评审 [H]#1 的武器化变体：ZipExtFile 读满声明值即 EOF 且
    CRC 校验通过，而单次全量解压的中间缓冲仍按物理输出膨胀（实测 ~2GiB）。
    """
    import zlib

    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    stream = co.compress(b'\x00' * nominal_out) + co.flush()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as zf:
        zf.writestr(member, stream)
    raw = bytearray(buf.getvalue())
    target = member.encode()
    # 计算截断前缀的 CRC（武器化变体用）
    prefix_crc = 0
    if crc_consistent:
        dec = zlib.decompressobj(-15)
        prefix = b''
        for i in range(0, len(stream), 64 * 1024):
            prefix += dec.decompress(stream[i:i + 64 * 1024], 64 * 1024)
            if len(prefix) >= declared:
                break
        prefix = prefix[:declared]
        prefix_crc = zlib.crc32(prefix)
    # (签名, compress_type 偏移, file_size 偏移, CRC 偏移, name_len 偏移, name 偏移)
    for sig, ctoff, fsoff, croff, nloff, noff in (
        (b'PK\x03\x04', 8, 22, 14, 26, 30),   # local file header
        (b'PK\x01\x02', 10, 24, 16, 28, 46),  # central directory
    ):
        pos = 0
        while (idx := raw.find(sig, pos)) >= 0:
            name_len = int.from_bytes(raw[idx + nloff:idx + nloff + 2], 'little')
            if bytes(raw[idx + noff:idx + noff + name_len]) == target:
                raw[idx + ctoff:idx + ctoff + 2] = (8).to_bytes(2, 'little')  # DEFLATED
                raw[idx + fsoff:idx + fsoff + 4] = declared.to_bytes(4, 'little')
                if crc_consistent:
                    raw[idx + croff:idx + croff + 4] = prefix_crc.to_bytes(4, 'little')
            pos = idx + 4
    return bytes(raw)


def test_underdeclared_member_rejected_by_physical_probe():
    """低报 file_size 的压缩炸弹必须被物理膨胀试探拦下（声明判定对它失明）。"""
    bomb = _make_underdeclared_bomb()
    with pytest.raises(XlsxBudgetError, match='声明不符'):
        assert_zip_budget(bomb)


def test_crc_consistent_underdeclared_bomb_still_rejected():
    """评审 [H]#1 武器化变体：CRC 与截断前缀一致也必须被物理计数拦下。

    旧试探经 ZipExtFile 计数（输出被声明 file_size 截断）对此变体失明；
    新试探直接解压原始压缩流计数物理输出——produced 是物理解压量而非
    截断值，与头部 CRC 无关。
    """
    bomb = _make_underdeclared_bomb(crc_consistent=True)
    with pytest.raises(XlsxBudgetError, match='声明不符'):
        assert_zip_budget(bomb)


def test_probe_lets_normal_workbook_through():
    """试探对正常工作簿零误报（合法压缩比 <10x，远低于 100:1 试探封顶）。"""
    assert_zip_budget(_make_xlsx(rows=50, cols=8))  # 比既有用例更大，确保试探真跑了


def test_read_member_bytes_low_peak_on_bomb():
    """分块读取低报成员的内存峰值必须远低于物理解压总量。

    变异检查锚点：把 _read_member_bytes 改回 zf.read() 后，峰值会逼近物理
    输出（64MiB 量级），本断言变红。
    """
    import contextlib
    import tracemalloc

    from fastapi_app.services.xlsx_cell_images import _read_member_bytes

    bomb = _make_underdeclared_bomb(member='xl/media/img1.png', nominal_out=64 * 1024 * 1024)
    tracemalloc.start()
    try:
        with zipfile.ZipFile(io.BytesIO(bomb)) as zf:
            # 截断输出与声明 CRC 不符 → BadZipFile（既有 400 口径）；峰值断言不受影响
            with contextlib.suppress(zipfile.BadZipFile):
                _read_member_bytes(zf, 'xl/media/img1.png')
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 16 * 1024 * 1024, (
        f'分块读的内存峰值应远低于物理解压总量 64MiB，实测 {peak / 2**20:.1f} MiB'
    )


# ---------------------------------------------------------------------------
# 工作簿层（openpyxl 链：裁剪 + 显式拒绝）
# ---------------------------------------------------------------------------

async def test_openpyxl_row_overflow_is_rejected_not_silently_dropped(monkeypatch):
    """行超限必须显式拒绝——静默丢行 = 数据无声丢失（用生产 _parse 函数验证）。"""
    from fastapi_app.services import production_summary_service as pss

    monkeypatch.setattr(xlsx_budget, 'MAX_SHEET_ROWS', 10)
    content = _make_xlsx(rows=15)
    with pytest.raises(XlsxBudgetError, match='行数'):
        await xlsx_budget.run_parse_with_timeout(
            xlsx_budget.parse_in_thread(pss._parse_packaging_rows, content))


async def test_openpyxl_col_overflow_is_rejected(monkeypatch):
    from fastapi_app.services import production_summary_service as pss

    monkeypatch.setattr(xlsx_budget, 'MAX_SHEET_COLS', 4)
    content = _make_xlsx(rows=2, cols=6)
    with pytest.raises(XlsxBudgetError, match='列数'):
        await xlsx_budget.run_parse_with_timeout(
            xlsx_budget.parse_in_thread(pss._parse_packaging_rows, content))


async def test_purchase_plan_staging_row_overflow_rejected(monkeypatch):
    from fastapi_app.services import purchase_plan_staging as pps

    monkeypatch.setattr(xlsx_budget, 'MAX_SHEET_ROWS', 5)
    content = _make_xlsx(rows=12)
    with pytest.raises(XlsxBudgetError, match='行数'):
        await xlsx_budget.run_parse_with_timeout(
            xlsx_budget.parse_in_thread(pps._load_excel_rows, content))


def test_assert_rows_within_budget_truth_table():
    assert_rows_within_budget(10, 5)  # 合界放行
    with pytest.raises(XlsxBudgetError, match='行数'):
        assert_rows_within_budget(xlsx_budget.MAX_SHEET_ROWS + 1, 5)
    with pytest.raises(XlsxBudgetError, match='列数'):
        assert_rows_within_budget(10, xlsx_budget.MAX_SHEET_COLS + 1)


# ---------------------------------------------------------------------------
# 时间层
# ---------------------------------------------------------------------------

async def test_parse_timeout_becomes_budget_error():
    async def slow():
        import asyncio as _aio
        await _aio.sleep(2)
        return 'never'

    with pytest.raises(XlsxBudgetError, match='超时'):
        await run_parse_with_timeout(slow(), timeout=0.05)


# ---------------------------------------------------------------------------
# Polars 链 + 单元格图片链
# ---------------------------------------------------------------------------

async def test_polars_chain_rejects_row_overflow_with_friendly_failure(monkeypatch, tmp_path):
    """综合导入（Polars）超限文件 → (False, [], 友好消息)，不抛异常。"""
    monkeypatch.setattr(xlsx_budget, 'MAX_SHEET_ROWS', 10)
    path = tmp_path / 'big.xlsx'
    path.write_bytes(_make_xlsx(rows=20))
    ok, data, msg = await batch_import_parser.parse_excel_file_async(str(path))
    assert ok is False and data == []
    assert '行数' in msg


async def test_polars_chain_rejects_zip_bomb(tmp_path):
    bomb = _zip_with({'xl/worksheets/sheet1.xml': b'\x00' * (8 * 1024 * 1024)})
    path = tmp_path / 'bomb.xlsx'
    path.write_bytes(bomb)
    ok, data, msg = await batch_import_parser.parse_excel_file_async(str(path))
    assert ok is False and data == []
    assert '压缩比' in msg


async def test_extract_cell_images_returns_empty_on_budget_violation(tmp_path):
    """图片提取前置预算未通过 → 空 dict（不阻断导入主流程，只留日志）。"""
    from fastapi_app.services.xlsx_cell_images import extract_cell_images

    bomb = _zip_with({'xl/cellimages.xml': b'<etc:cellImage></etc:cellImage>' * 10,
                      'xl/_rels/cellimages.xml.rels': b'\x00' * (8 * 1024 * 1024)})
    path = tmp_path / 'bomb.xlsx'
    path.write_bytes(bomb)
    assert extract_cell_images(str(path)) == {}


async def test_extract_cell_images_normal_workbook_still_empty(tmp_path):
    """正常无图片工作簿 → 空 dict（预算放行，行为不变）。"""
    from fastapi_app.services.xlsx_cell_images import extract_cell_images

    path = tmp_path / 'plain.xlsx'
    path.write_bytes(_make_xlsx())
    assert extract_cell_images(str(path)) == {}


# ---------------------------------------------------------------------------
# 端点层：预算拒绝必须落成 400（评审 finding 3），不得 500
# ---------------------------------------------------------------------------

async def test_packaging_upload_budget_violation_is_400(client, monkeypatch):
    """包装部上传链：service 层抛 XlsxBudgetError → 端点转 400（而非全局 500）。"""
    from unittest.mock import AsyncMock

    from fastapi_app.services import production_summary_service

    monkeypatch.setattr(
        production_summary_service, 'upload_packaging_excel',
        AsyncMock(side_effect=XlsxBudgetError('文件解压后总量过大（999999999 字节，上限 134217728）')),
    )
    resp = await client.post(
        '/api/v1/production-summary/packaging/upload',
        files={'file': ('b.xlsx', b'PK\x03\x04' + b'0' * 100,
                        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
    )
    assert resp.status_code == 400, (
        f'预算拒绝必须 400 且带可读原因，实际 {resp.status_code} {resp.text[:150]}'
    )
    assert '上限' in resp.json()['detail']


async def test_production_plan_upload_budget_violation_is_400(client, monkeypatch):
    """生产计划上传链：XlsxBudgetError → 400。"""
    from unittest.mock import AsyncMock

    from fastapi_app.services import production_plan_service

    monkeypatch.setattr(
        production_plan_service, 'upload_excel',
        AsyncMock(side_effect=XlsxBudgetError('文件压缩比异常（999:1，上限 100:1），疑似压缩炸弹')),
    )
    resp = await client.post(
        '/api/v1/production-plans/upload',
        files={'file': ('b.xlsx', b'PK\x03\x04' + b'0' * 100,
                        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
    )
    assert resp.status_code == 400, (
        f'预算拒绝必须 400，实际 {resp.status_code} {resp.text[:150]}'
    )
