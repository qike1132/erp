#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
库存多年期模拟 —— 公共模块

提供：
- SimAPIClient：httpx.AsyncClient 封装，BaseURL 指向生产 API，含限速、重试、
  401 自动重登。所有 HTTP 操作统一由此发出。
- JournalWriter：journal 落盘（ops.jsonl / checkpoints.json / summary.json）。
- 常量 PREFIX / SEED / TIME_SPAN 供 simulator/verifier/cleanup 共享。

本模块独立运行，不 import 项目业务代码，仅依赖标准库 + httpx。
凭据从环境变量 ERP_SIM_USER / ERP_SIM_PASSWORD 读取。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, timedelta

import httpx

logger = logging.getLogger("stock_sim")

PREFIX = "SIMTEST"
SEED = 20260910
BASE_URL = os.environ.get("ERP_SIM_BASE_URL", "http://192.168.0.95:3000/api/v1")
TIME_SPAN = ("2026-09-01", "2029-09-01")
RATE_LIMIT_MS = 80  # 操作间限速
CHECKPOINT_FILE = "checkpoints.json"
SUMMARY_FILE = "summary.json"
OPS_FILE = "ops.jsonl"


class SimError(Exception):
    """模拟脚本内部错误"""


class SimAPIClient:
    """对生产 API 的异步封装：限速 + 重试 + 401 自动重登。"""

    def __init__(self, username: str, password: str, base_url: str = BASE_URL,
                 rate_limit_ms: int = RATE_LIMIT_MS):
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.rate_limit_ms = rate_limit_ms
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        self._token = None
        self._logged_in = False

    async def _sleep(self):
        if self.rate_limit_ms > 0:
            await asyncio.sleep(self.rate_limit_ms / 1000.0)

    async def login(self) -> None:
        """使用账号密码登录，缓存 access_token。"""
        resp = await self._client.post(
            f"{self.base_url}/auth/login",
            json={"username": self.username, "password": self.password, "remember": True},
        )
        if resp.status_code != 200:
            raise SimError(f"登录失败 HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise SimError(f"登录响应缺少 access_token: {data}")
        self._token = token
        self._logged_in = True
        logger.info("已登录：%s", self.username)

    async def close(self):
        await self._client.aclose()

    async def _send(self, method: str, path: str, max_retries: int = 3, **kw) -> httpx.Response:
        url = f"{self.base_url}{path}"
        headers = dict(kw.pop("headers", {}))
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        attempt = 0
        while True:
            attempt += 1
            await self._sleep()
            resp = await self._client.request(method, url, headers=headers, **kw)
            if resp.status_code == 401 and self._logged_in and attempt <= max_retries:
                logger.info("Token 失效(401)，自动重新登录")
                await self.login()
                headers["Authorization"] = f"Bearer {self._token}"
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt <= max_retries:
                wait = min(2 ** attempt, 8)
                logger.warning("%s %s -> %s，%ss 后重试(%d/%d)", method, path,
                               resp.status_code, wait, attempt, max_retries)
                await asyncio.sleep(wait)
                continue
            return resp

    async def get(self, path: str, params: dict | None = None) -> httpx.Response:
        return await self._send("GET", path, params=params)

    async def post(self, path: str, json: dict | None = None) -> httpx.Response:
        return await self._send("POST", path, json=json)

    async def put(self, path: str, json: dict | None = None) -> httpx.Response:
        return await self._send("PUT", path, json=json)

    async def delete(self, path: str) -> httpx.Response:
        return await self._send("DELETE", path)

    # ---- 便捷业务方法 ----
    async def create_product(self, name: str) -> int:
        """创建产品并反查其 id。create 响应不含 id，用 search 按唯一名反查。"""
        r = await self.post("/products/create", json={"name": name, "price": 0, "initial_stock": 0})
        if r.status_code not in (200, 201):
            raise SimError(f"创建产品失败 {r.status_code}: {r.text[:300]}")
        for _ in range(5):
            s = await self.get("/aux/product-search", {"q": name})
            if s.status_code == 200:
                items = s.json()
                if isinstance(items, list) and items:
                    match = items[0]
                    return int(match.get("id") or match.get("product_id"))
            await asyncio.sleep(0.5)
        raise SimError(f"产品创建后无法反查 id：{name}")

    async def delete_product(self, product_id: int) -> bool:
        r = await self.delete(f"/products/delete/{product_id}")
        return r.status_code in (200, 201)

    async def create_order(self, product_id: int, quantity: int, customer: str,
                           order_type: str, country: str | None, order_date: str,
                           note: str) -> httpx.Response:
        body = {"product_id": product_id, "quantity": quantity, "customer": customer,
                "order_type": order_type, "order_date": order_date, "note": note}
        if country:
            body["country"] = country
        return await self.post("/orders/create", json=body)

    async def create_stockin(self, product_id: int, quantity: int, customer: str,
                             stockin_date: str, note: str) -> httpx.Response:
        return await self.post("/stock/in/create", json={
            "product_id": product_id, "quantity": quantity, "customer": customer,
            "stockin_date": stockin_date, "note": note})

    async def edit_stockin(self, stockin_id: int, quantity: int, customer: str,
                           stockin_date: str, note: str) -> httpx.Response:
        return await self.put(f"/stock/in/edit/{stockin_id}", json={
            "quantity": quantity, "customer": customer, "stockin_date": stockin_date,
            "note": note})

    async def delete_stockin(self, stockin_id: int) -> httpx.Response:
        return await self.delete(f"/stock/in/delete/{stockin_id}")

    async def create_stockout(self, product_id: int, quantity: int, customer: str,
                              stockout_date: str, note: str, order_type: str,
                              country: str | None) -> httpx.Response:
        body = {"product_id": product_id, "quantity": quantity, "customer": customer,
                "stockout_date": stockout_date, "note": note, "order_type": order_type}
        if country:
            body["country"] = country
        return await self.post("/stock/out/create", json=body)

    async def delete_stockout(self, stockout_id: int) -> httpx.Response:
        return await self.delete(f"/stock/out/delete/{stockout_id}")

    async def available_shipment(self, product_id: int, customer: str,
                                 order_type: str | None = None,
                                 country: str | None = None) -> dict:
        params = {"product_id": product_id, "customer": customer}
        if order_type:
            params["order_type"] = order_type
        if country:
            params["country"] = country
        r = await self.get("/aux/available-shipment", params)
        if r.status_code != 200:
            raise SimError(f"available-shipment 失败 {r.status_code}: {r.text[:300]}")
        return r.json()

    async def product_available_stock(self, product_id: int) -> dict:
        r = await self.get("/aux/product-available-stock", {"product_id": product_id})
        if r.status_code not in (200, 404):
            raise SimError(f"product-available-stock 失败 {r.status_code}: {r.text[:300]}")
        return r.json() if r.status_code == 200 else {}

    async def inventory_logs(self, product_id: int, per_page: int = 200) -> list[dict]:
        """分页拉取产品全部库存流水。"""
        out, page = [], 1
        while True:
            r = await self.get(f"/aux/inventory-logs/{product_id}",
                               {"page": page, "per_page": per_page})
            if r.status_code != 200:
                raise SimError(f"inventory-logs 失败 {r.status_code}: {r.text[:300]}")
            data = r.json()
            items = data.get("items") or []
            out.extend(items)
            total = data.get("total", 0)
            if page * per_page >= total or not items:
                break
            page += 1
        return out

    async def stockin_list(self, customer: str, per_page: int = 500) -> list[dict]:
        return await self._paginate("/stock/in/list", "items", customer, per_page)

    async def stockout_list(self, customer: str, per_page: int = 500) -> list[dict]:
        return await self._paginate("/stock/out/list", "items", customer, per_page)

    async def order_list(self, customer: str, per_page: int = 500) -> list[dict]:
        return await self._paginate("/orders/list", "data", customer, per_page)

    async def _paginate(self, path: str, items_key: str, customer: str,
                        per_page: int) -> list[dict]:
        out, page = [], 1
        while True:
            r = await self.get(path, {"customer": customer, "page": page, "per_page": per_page})
            if r.status_code != 200:
                raise SimError(f"{path} 失败 {r.status_code}: {r.text[:300]}")
            data = r.json()
            items = data.get(items_key, data.get("data", [])) or []
            out.extend(items)
            total = data.get("total", 0)
            if page * per_page >= total or not items:
                break
            page += 1
        return out

    async def inventory(self, customer: str, per_page: int = 200) -> dict:
        r = await self.get("/stock/inventory", {"customer": customer, "per_page": per_page})
        if r.status_code != 200:
            raise SimError(f"inventory 失败 {r.status_code}: {r.text[:300]}")
        return r.json()

    async def stats(self) -> dict:
        r = await self.get("/stock/stats")
        if r.status_code != 200:
            raise SimError(f"stats 失败 {r.status_code}: {r.text[:300]}")
        return r.json()


class JournalWriter:
    """journal 落盘：ops.jsonl 逐行追加、checkpoints.json、summary.json。"""

    def __init__(self, run_dir: str):
        self.run_dir = run_dir
        os.makedirs(run_dir, exist_ok=True)
        self.ops_path = os.path.join(run_dir, OPS_FILE)
        self.checkpoints_path = os.path.join(run_dir, CHECKPOINT_FILE)
        self.summary_path = os.path.join(run_dir, SUMMARY_FILE)
        self._checkpoints: list[dict] = []

    def append_op(self, op: dict) -> None:
        with open(self.ops_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(op, ensure_ascii=False, default=str) + "\n")

    def add_checkpoint(self, cp: dict) -> None:
        self._checkpoints.append(cp)
        with open(self.checkpoints_path, "w", encoding="utf-8") as f:
            json.dump(self._checkpoints, f, ensure_ascii=False, indent=2, default=str)

    def write_summary(self, summary: dict) -> None:
        with open(self.summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    def read_checkpoints(self) -> list[dict]:
        if os.path.exists(self.checkpoints_path):
            with open(self.checkpoints_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def read_summary(self) -> dict:
        if os.path.exists(self.summary_path):
            with open(self.summary_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}


def daterange(start: str, end: str) -> list[date]:
    """返回 [start, end] 之间的所有日（含两端）。"""
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    out = []
    cur = s
    while cur <= e:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def is_last_day_of_month(d: date) -> bool:
    nxt = d + timedelta(days=1)
    return nxt.month != d.month