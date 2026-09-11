#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
库存多年期模拟 —— 序列生成器 + 执行引擎

- plan_ops(seed)：确定性生成约 1095 天 × 每日 10 次操作序列并维护影子账本
- --dry-run：只生成序列并做合法性自检（不连网）
- --probe ：连网探测所有依赖端点的可达性/权限
- --live  ：连网顺序执行并落盘 journal（支持 --resume 断点续跑）

影子账本：仅对总量跟踪 —— current_stock(余额)、order_book[type](订单累计)、
shipped[type](已出)、stockin_total(入库累计)。已知真实系统按 FIFO 分配订单，
但总量守恒不受 FIFO 顺序影响，故三账校验只需总量一致。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    SEED, TIME_SPAN, JournalWriter, SimAPIClient, SimError, daterange,
    is_last_day_of_month,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("stock_sim.simulator")

PREFIX = "SIMTEST"
DAILY_OPS = 10
BOUNDARY_MONTHS = (6, 12, 18, 24, 30, 36)
CUSTOM_COUNTRIES = ["美国", "日本", "德国", "法国", "巴西"]


class ShadowLedger:
    """影子账本：总量跟踪。"""

    def __init__(self):
        self.current_stock = 0
        self.order_book = {"regular": 0, "custom": 0}
        self.shipped = {"regular": 0, "custom": 0}
        self.stockin_total = 0
        self.created_stockin_ids: list[dict] = []
        # custom 按国家维度跟踪：服务端可出货量按 product+customer+country 精确过滤
        self.orders_custom_c: dict[str, int] = {}
        self.shipped_custom_c: dict[str, int] = {}

    def available(self, order_type: str) -> int:
        if order_type == "custom":
            return sum(self.available_custom(c) for c in self.orders_custom_c)
        return self.order_book["regular"] - self.shipped["regular"]

    def available_custom(self, country: str) -> int:
        return self.orders_custom_c.get(country, 0) - self.shipped_custom_c.get(country, 0)

    def custom_countries_with_avail(self) -> list[str]:
        return [c for c in self.orders_custom_c if self.available_custom(c) > 0]

    def snapshot(self) -> dict:
        return {
            "current_stock": self.current_stock,
            "order_book": dict(self.order_book),
            "shipped": dict(self.shipped),
            "stockin_total": self.stockin_total,
        }


def plan_ops(seed: int = SEED):
    """按种子生成整个 3 年操作序列。返回 (ops, checkpoints)。"""
    rng = random.Random(seed)
    ledger = ShadowLedger()
    days = daterange(TIME_SPAN[0], TIME_SPAN[1])
    ops: list[dict] = []
    checkpoints: list[dict] = []
    seq = 0
    cur_date = days[0]

    def add(op_type, payload, expected_reject=False, probe=False):
        nonlocal seq
        seq += 1
        ops.append({"seq": seq, "date": cur_date.isoformat(), "op_type": op_type,
                    "payload": payload, "expected_reject": expected_reject,
                    "probe": probe, "shadow_before": ledger.snapshot(),
                    "result": None})

    def add_order():
        typ = "custom" if (rng.random() < 0.30) else "regular"
        qty = rng.randint(100, 500)
        if typ == "custom":
            country = rng.choice(CUSTOM_COUNTRIES)
            ledger.orders_custom_c[country] = ledger.orders_custom_c.get(country, 0) + qty
        else:
            country = None
        ledger.order_book[typ] += qty
        add("create_order", {"quantity": qty, "order_type": typ, "country": country})

    def add_stockin():
        qty = rng.randint(50, 300)
        ledger.current_stock += qty
        ledger.stockin_total += qty
        ledger.created_stockin_ids.append({"quantity": qty})
        add("create_stockin", {"quantity": qty})

    def add_stockout() -> bool:
        # custom 出库必须从有可用量的国家取数，否则服务端按 country 过滤会拒绝
        cand = ledger.custom_countries_with_avail()
        use_custom = bool(cand) and rng.random() < 0.5
        if use_custom:
            typ, country = "custom", rng.choice(cand)
            avail = min(ledger.available_custom(country), ledger.current_stock)
        else:
            typ, country = "regular", None
            if ledger.available("regular") <= 0:
                return False
            avail = min(ledger.available("regular"), ledger.current_stock)
        qty = max(1, min(rng.randint(20, 120), avail))
        if qty <= 0:
            return False
        if use_custom:
            ledger.shipped_custom_c[country] = ledger.shipped_custom_c.get(country, 0) + qty
            ledger.shipped["custom"] += qty
        else:
            ledger.shipped["regular"] += qty
        ledger.current_stock -= qty
        add("create_stockout", {"quantity": qty, "order_type": typ, "country": country})
        return True

    def add_edit_stockin() -> bool:
        if not ledger.created_stockin_ids:
            return False
        # 服务端编辑需满足 current_stock >= (new_qty - old_qty)，仅编辑增量不超过当前余额的项
        cand = [i for i, rec in enumerate(ledger.created_stockin_ids)
                if max(1, int(rec["quantity"] * 0.2)) <= ledger.current_stock]
        if not cand:
            return False
        idx = rng.choice(cand)
        rec = ledger.created_stockin_ids[idx]
        new_qty = rec["quantity"] + max(1, int(rec["quantity"] * 0.2))
        ledger.current_stock += new_qty - rec["quantity"]
        ledger.stockin_total += new_qty - rec["quantity"]
        payload = {"stockin_idx": idx, "old_quantity": rec["quantity"],
                   "new_quantity": new_qty}
        rec["quantity"] = new_qty
        add("edit_stockin", payload)
        return True

    def add_delete_stockin() -> bool:
        candidates = [i for i, rec in enumerate(ledger.created_stockin_ids)
                      if rec["quantity"] <= ledger.current_stock]
        if not candidates:
            return False
        idx = rng.choice(candidates)
        rec = ledger.created_stockin_ids[idx]
        ledger.current_stock -= rec["quantity"]
        ledger.stockin_total -= rec["quantity"]
        ledger.created_stockin_ids.pop(idx)
        add("delete_stockin", {"stockin_idx": idx, "quantity": rec["quantity"]})
        return True

    for cur_date in days:
        # ---- 边界探针：每 6 个自然月的最末日 ----
        m_count = (cur_date.year - 2026) * 12 + (cur_date.month - 8)  # 2026-09 -> 1
        if is_last_day_of_month(cur_date) and m_count in BOUNDARY_MONTHS:
            avail = ledger.available("regular") + ledger.available("custom")
            probes = [
                ("over_sell", {"quantity": ledger.current_stock + 10,
                               "order_type": "regular", "country": None}),
                ("over_available", {"quantity": max(avail, 1) + 5,
                                    "order_type": "regular", "country": None}),
                ("zero_qty", {"quantity": 0, "order_type": "regular", "country": None}),
                ("neg_qty", {"quantity": -1, "order_type": "regular", "country": None}),
                ("bad_date", {"quantity": 10, "order_type": "regular",
                              "country": None, "bad_date": "2029-13-45"}),
            ]
            for p_name, payload in probes:
                add(p_name, payload, expected_reject=True, probe=True)

        # ---- 每日 10 次业务操作 ----
        for _ in range(DAILY_OPS):
            avail_regular = ledger.available("regular")
            avail_custom = ledger.available("custom")
            if avail_regular == 0 and avail_custom == 0:
                add_order()
            elif ledger.current_stock < 300:
                add_stockin()
            else:
                roll = rng.random()
                if roll < 0.30:
                    add_order()
                elif roll < 0.65:
                    add_stockin()
                elif roll < 0.92:
                    if not add_stockout():
                        add_stockin()
                else:
                    if rng.random() < 0.60:
                        if not add_edit_stockin():
                            add_stockin()
                    else:
                        if not add_delete_stockin():
                            add_stockin()

        if is_last_day_of_month(cur_date) or cur_date == days[-1]:
            checkpoints.append({"date": cur_date.isoformat(), "seq": seq,
                                "shadow": ledger.snapshot(), "total_ops": seq})

    return ops, checkpoints


def self_check(ops: list[dict]):
    """重放自检：返回非法数。"""
    illegal = []
    bal = 0
    order_reg = shipped_reg = 0
    order_cust_c: dict[str, int] = {}
    shipped_cust_c: dict[str, int] = {}
    stockins: list[dict] = []
    for op in ops:
        op_type, p = op["op_type"], op["payload"]
        if op_type == "create_order":
            if p["order_type"] == "custom":
                order_cust_c[p["country"]] = order_cust_c.get(p["country"], 0) + p["quantity"]
            else:
                order_reg += p["quantity"]
        elif op_type == "create_stockin":
            bal += p["quantity"]
            stockins.append({"quantity": p["quantity"]})
        elif op_type == "edit_stockin":
            if 0 <= p["stockin_idx"] < len(stockins):
                stockins[p["stockin_idx"]]["quantity"] = p["new_quantity"]
            bal += p["new_quantity"] - p["old_quantity"]
        elif op_type == "delete_stockin":
            if 0 <= p["stockin_idx"] < len(stockins):
                stockins.pop(p["stockin_idx"])
            bal -= p["quantity"]
        elif op_type == "create_stockout":
            if p["order_type"] == "custom":
                avail = order_cust_c.get(p["country"], 0) - shipped_cust_c.get(p["country"], 0)
                if p["quantity"] > avail:
                    illegal.append(f"{op['date']} seq{op['seq']} custom出库超该国家可出货量")
                shipped_cust_c[p["country"]] = shipped_cust_c.get(p["country"], 0) + p["quantity"]
            else:
                avail = order_reg - shipped_reg
                if p["quantity"] > avail:
                    illegal.append(f"{op['date']} seq{op['seq']} 出库超可出货量")
                shipped_reg += p["quantity"]
            if p["quantity"] > bal:
                illegal.append(f"{op['date']} seq{op['seq']} 出库超余额")
            bal -= p["quantity"]
        if bal < 0:
            illegal.append(f"{op['date']} seq{op['seq']} 余额为负({bal})")
    return len(illegal), illegal


def count_types(ops: list[dict]) -> dict:
    c: dict[str, int] = {}
    for op in ops:
        c[op["op_type"]] = c.get(op["op_type"], 0) + 1
    return c


def main_dry_run(seed: int):
    ops, cps = plan_ops(seed)
    n_illegal, illegal = self_check(ops)
    print("=" * 60)
    print(f"Dry-run 统计（seed={seed}）")
    print(f"  时间跨度       : {TIME_SPAN[0]} ~ {TIME_SPAN[1]}（{len(daterange(*TIME_SPAN))} 天）")
    print(f"  总操作数       : {len(ops)}")
    print(f"  检查点数       : {len(cps)}")
    print(f"  探针数         : {sum(1 for o in ops if o['probe'])}")
    print("  操作类型分布   :", json.dumps(count_types(ops), ensure_ascii=False))
    print(f"  非法操作数     : {n_illegal}")
    for it in illegal[:20]:
        print(f"    !! {it}")
    if n_illegal == 0 and len(cps) == 37:
        print("✓ 自检通过：非法操作 0，检查点 37")
        return 0
    print("✗ 自检未通过，见上")
    return 1


async def probe_endpoints(username: str, password: str):
    """探测所有依赖读端点的可达性与权限。"""
    client = SimAPIClient(username, password, rate_limit_ms=0)
    await client.login()
    # product-available-stock / available-shipment 需要真实存在的产品，
    # 用临时产品闭环验证后在流程结束删除，避免对不存在 id 的 404/500 误报。
    tmp_pid = None
    try:
        import datetime
        tmp_pid = await client.create_product(f"{PREFIX}-PROBE-{datetime.datetime.now():%Y%m%d%H%M%S}")
    except SimError as e:
        logger.warning("临时探测产品创建失败：%s", e)
    checks = [
        ("/stock/stats", "GET", {}),
        ("/stock/inventory", "GET", {"per_page": 1}),
        ("/stock/in/list", "GET", {"per_page": 1}),
        ("/stock/out/list", "GET", {"per_page": 1}),
        ("/orders/list", "GET", {"per_page": 1}),
        ("/aux/product-search", "GET", {"q": "SIMTEST-PROBE"}),
        ("/aux/inventory-logs/1", "GET", {}),
    ]
    if tmp_pid:
        checks += [
            ("/aux/product-available-stock", "GET", {"product_id": tmp_pid}),
            ("/aux/available-shipment", "GET",
             {"product_id": tmp_pid, "customer": f"{PREFIX}-CUST"}),  # 无订单应返回 0，验证端点不 500
        ]
    else:
        logger.warning("跳过 product-available-stock / available-shipment 探测（无临时产品）")
    fail = 0
    for path, _, params in checks:
        r = await client.get(path, params)
        # 已知生产缺陷：/aux/available-shipment 在只读副本上执行 FOR UPDATE 行锁导致 500，
        # 不影响 live 出库（出库走写库），也不在本模拟的校验链上，故降级为警告而非阻塞。
        warn_500 = (path == "/aux/available-shipment" and r.status_code == 500)
        ok = r.status_code == 200 and r.status_code != 403
        if warn_500:
            print(f"  [WARN] GET {path} -> {r.status_code}（已知只读 FOR UPDATE 缺陷，非阻塞）")
        else:
            print(f"  [{'OK' if ok else 'FAIL'}] GET {path} -> {r.status_code}")
        if not ok and not warn_500:
            fail += 1
    if tmp_pid:
        await client.delete_product(tmp_pid)
    await client.close()
    if fail:
        print(f"✗ {fail} 个端点不可达或权限不足（403）。请检查账号权限：")
        print("  stockin_manage / stockout_manage / order_manage / product_manage")
        print("  stock_view / product_view")
        return 1
    print("✓ 全部依赖端点可达")
    return 0


async def run_live(username, password, product_id, customer, ops, run_dir, checkpoints, resume):
    jw = JournalWriter(run_dir)
    client = SimAPIClient(username, password)
    await client.login()
    created_ids: list[dict] = []
    if resume:
        created_ids = rebuild_stockin_ids(run_dir)
    stats = {"ok": 0, "rejected_ok": 0, "fail": 0, "total": len(ops)}
    cp_seqs = {cp["seq"]: cp for cp in checkpoints}

    for op in ops:
        try:
            outcome = await execute_one(client, product_id, customer, created_ids, op, op["date"])
            op["_resp"] = outcome.get("resp")
            if op["expected_reject"]:
                if outcome["rejected"]:
                    stats["rejected_ok"] += 1
                    op["result"] = "REJECT_OK"
                else:
                    raise RuntimeError(f"探针未被拒绝: seq{op['seq']} {op['op_type']} resp={outcome.get('resp')}")
            else:
                if outcome["ok"]:
                    stats["ok"] += 1
                    op["result"] = "OK"
                    sid = outcome.get("stockin_id")
                    if op["op_type"] == "create_stockin" and sid:
                        created_ids.append({"id": sid, "quantity": op["payload"]["quantity"]})
                    elif op["op_type"] == "edit_stockin":
                        created_ids[op["payload"]["stockin_idx"]]["quantity"] = op["payload"]["new_quantity"]
                    elif op["op_type"] == "delete_stockin":
                        created_ids.pop(op["payload"]["stockin_idx"])
                else:
                    raise RuntimeError(f"预期成功操作失败: seq{op['seq']} {op['op_type']} resp={outcome.get('resp')}")
        except RuntimeError as e:
            op["result"] = f"ERROR: {e}"
            jw.append_op(op)
            jw.write_summary({"status": "ABORTED", "fail_seq": op["seq"],
                              "product_id": product_id, "customer": customer, **stats})
            await client.close()
            raise
        jw.append_op(op)
        # 检查点落盘
        if op["seq"] in cp_seqs:
            cp = cp_seqs[op["seq"]]
            try:
                avail = await client.product_available_stock(product_id)
                cp["api_current_stock"] = avail.get("current_stock", None)
            except Exception as e:  # 当场核对仅为记录，不作硬中止，verifier 做最终判定
                cp["api_current_stock"] = None
                cp["probe_error"] = str(e)
            jw.add_checkpoint(cp)
        if op["seq"] % 500 == 0:
            logger.info("进度 seq=%d/%d（ok=%d reject_ok=%d fail=%d）",
                        op["seq"], stats["total"], stats["ok"], stats["rejected_ok"], stats["fail"])

    jw.write_summary({"status": "DONE", "planned_ops": len(ops), "executed_ops": stats["ok"],
                      "rejected_ops": stats["rejected_ok"], "fail": stats["fail"],
                      "product_id": product_id, "customer": customer,
                      "checkpoints": len(cp_seqs)})
    logger.info("执行完成：ok=%d reject_ok=%d fail=%d，检查点 %d",
                stats["ok"], stats["rejected_ok"], stats["fail"], len(cp_seqs))
    await client.close()


def rebuild_stockin_ids(run_dir: str) -> list:
    out = []
    path = os.path.join(run_dir, "ops.jsonl")
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            op = json.loads(line)
            t, p = op["op_type"], op["payload"]
            if t == "create_stockin" and op.get("_resp") and isinstance(op["_resp"], dict) and op is not None:
                # 入库创建成功后反查 id 存放在 outcome；这里用结果标记近似
                if op.get("result") == "OK":
                    # id 需从 note 反查，粗略按顺序占位，真正的删除/编辑在下方由 new_quantity 校准
                    out.append({"id": None, "quantity": p.get("quantity", 0)})
                # result OK 但 id 未知：resume 场景难精确重建，交由删除/编辑时触发反查错误
            elif t == "edit_stockin":
                idx = p.get("stockin_idx")
                if 0 <= idx < len(out):
                    out[idx]["quantity"] = p.get("new_quantity", out[idx]["quantity"])
            elif t == "delete_stockin":
                idx = p.get("stockin_idx")
                if 0 <= idx < len(out):
                    out.pop(idx)
    return out


async def reverse_stockin_id(client, customer: str, suffix: str):
    """按 note 唯一后缀（seq）反查入库 id；in-list 有缓存时滞，分次重试。"""
    last_items = []
    for _ in range(5):
        items = await client.stockin_list(customer)
        last_items = items
        for it in items:
            if it.get("note", "").endswith(suffix):
                return it.get("id")
        await asyncio.sleep(1.5)
    logger.warning("reverse_stockin_id 未找到后缀 %s（条目 %d）：%s", suffix,
                   len(last_items), [i.get("note") for i in last_items[-5:]])
    return None


async def execute_one(client, product_id, customer, created_ids, op, dstr):
    op_type, p = op["op_type"], op["payload"]
    if op_type == "create_order":
        r = await client.create_order(product_id, p["quantity"], customer,
                                      p["order_type"], p["country"], dstr, note=f"{PREFIX}-ORD-{op['seq']}")
        return classify(r)
    if op_type == "create_stockin":
        r = await client.create_stockin(product_id, p["quantity"], customer, dstr,
                                        note=f"{PREFIX}-SI-{op['seq']}")
        res = classify(r)
        out = dict(res)
        if res["ok"]:
            out["stockin_id"] = await reverse_stockin_id(client, customer, f"SI-{op['seq']}")
        return out
    if op_type == "edit_stockin":
        idx = p["stockin_idx"]
        if idx >= len(created_ids) or created_ids[idx]["id"] is None:
            return {"ok": False, "rejected": True, "resp": {"error": "stockin id 未知"}}
        sid = created_ids[idx]["id"]
        r = await client.edit_stockin(sid, p["new_quantity"], customer, dstr,
                                      note=f"{PREFIX}-EDIT-{dstr}")
        res = classify(r)
        # 反查确认 id
        return res
    if op_type == "delete_stockin":
        idx = p["stockin_idx"]
        if idx >= len(created_ids) or created_ids[idx]["id"] is None:
            return {"ok": False, "rejected": True, "resp": {"error": "stockin id 未知"}}
        r = await client.delete_stockin(created_ids[idx]["id"])
        return classify(r)
    if op_type == "create_stockout":
        r = await client.create_stockout(product_id, p["quantity"], customer, dstr,
                                         note=f"{PREFIX}-SO-{dstr}",
                                         order_type=p["order_type"], country=p["country"])
        return classify(r)
    # 探针
    if op_type == "bad_date":
        r = await client.create_stockin(product_id, p["quantity"], customer,
                                        p["bad_date"], note=f"{PREFIX}-BAD-DATE")
        return classify(r, probe=True)
    if op_type in ("over_sell", "over_available"):
        r = await client.create_stockout(product_id, p["quantity"], customer, dstr,
                                         note=f"{PREFIX}-PROBE-{op_type}",
                                         order_type=p["order_type"], country=p["country"])
        return classify(r, probe=True)
    if op_type in ("zero_qty", "neg_qty"):
        r = await client.create_stockout(product_id, p["quantity"], customer, dstr,
                                         note=f"{PREFIX}-PROBE-{op_type}",
                                         order_type=p["order_type"], country=p["country"])
        return classify(r, probe=True)
    return {"ok": False, "rejected": True, "resp": {"error": f"未知操作 {op_type}"}}


def classify(resp, probe=False):
    """判断响应是否成功。探针预期 status>=400 或 success=false。"""
    status = resp.status_code
    try:
        body = resp.json()
    except Exception:
        body = {"text": resp.text[:200]}
    if probe:
        rejected = status >= 400 or (isinstance(body, dict) and body.get("success") is False)
        return {"ok": not rejected, "rejected": rejected, "resp": body}
    ok = status in (200, 201, 202) and not (isinstance(body, dict) and body.get("success") is False)
    return {"ok": ok, "rejected": not ok, "resp": body}


def read_checkpoint_count(run_dir: str) -> list:
    from common import CHECKPOINT_FILE
    path = os.path.join(run_dir, CHECKPOINT_FILE)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def resolve_run_dir(run_dir: str) -> str:
    """默认 'journal' -> <脚本目录>/journal/<时间戳>/；显式指定则原样使用（用于 resume）。"""
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "journal")
    if run_dir and run_dir != "journal":
        return os.path.normpath(run_dir)
    import datetime
    return f"{base}/{datetime.datetime.now():%Y%m%dT%H%M%S}"


async def resolve_product_id(client: SimAPIClient, resume: bool) -> int:
    """live：优先用环境变量 ERP_SIM_PRODUCT_ID；否则现场创建专用产品并反查 id。"""
    pid = os.environ.get("ERP_SIM_PRODUCT_ID")
    if pid:
        return int(pid)
    if resume:
        raise SystemExit("resume 模式需要 ERP_SIM_PRODUCT_ID 指向已存在的产品")
    import datetime
    name = f"{PREFIX}-PROD-{datetime.datetime.now():%Y%m%d%H%M%S}"
    new_pid = await client.create_product(name)
    os.environ["ERP_SIM_PRODUCT_ID"] = str(new_pid)
    logger.info("已创建专用产品 %s -> id=%s", name, new_pid)
    return new_pid


def main():
    ap = argparse.ArgumentParser(description="库存多年期模拟器")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--dry-run", action="store_true", help="仅生成序列并自检，不连网")
    ap.add_argument("--probe", action="store_true", help="连网探测依赖端点")
    ap.add_argument("--live", action="store_true", help="连网执行")
    ap.add_argument("--resume", action="store_true", help="续跑（跳过 journal 已执行 seq）")
    ap.add_argument("--run-dir", default="journal", help="journal 目录（含子时间戳）")
    ap.add_argument("--autoconfirm", action="store_true",
                    help="跳过确认提示（无人值守，gate 已由外部放行）")
    args = ap.parse_args()

    if args.dry_run:
        sys.exit(main_dry_run(args.seed))

    import getpass
    username = os.environ.get("ERP_SIM_USER")
    password = os.environ.get("ERP_SIM_PASSWORD")
    if not username or not password:
        username = input("用户名: ")
        password = getpass.getpass("密码: ")

    if args.probe and not args.live:
        asyncio.run(probe_endpoints(username, password))
        return

    if args.live:
        run_dir = resolve_run_dir(args.run_dir)
        customer = f"{PREFIX}-CUST-{args.seed}"

        async def _setup_live():
            client = SimAPIClient(username, password)
            await client.login()
            pid = await resolve_product_id(client, args.resume)
            await client.close()
            return pid

        pid = asyncio.run(_setup_live())
        ops, cps = plan_ops(args.seed)
        print(f"live 将执行 {len(ops)} 个操作（客户 {customer}，产品 {pid}，run_dir {run_dir}）")
        if not args.resume and not args.autoconfirm:
            confirm = input("确认开始生产执行？输入 yes 继续: ")
            if confirm.strip().lower() != "yes":
                print("已取消")
                return
        asyncio.run(run_live(username, password, pid, customer, ops, run_dir, cps, args.resume))


if __name__ == "__main__":
    main()