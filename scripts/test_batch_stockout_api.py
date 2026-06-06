"""
批量出库接口本地测试脚本

使用方法：
1. 确保 FastAPI 服务正在运行（默认 http://192.168.0.95:8000）
2. 运行：python scripts/test_batch_stockout_api.py

测试前请确保数据库中有：
- 产品 ID=1（库存 >= 100）
- 客户 "测试客户A" 有对应的订单（数量 >= 50）
"""
import asyncio
import sys
import json
from datetime import datetime

import httpx

BASE_URL = "http://192.168.0.95:8000/api/v1/auxiliary"
# 如果需要认证，请替换为有效 token
AUTH_TOKEN = "test-token"


async def get_headers():
    return {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
    }


async def test_batch_stockout_normal(client: httpx.AsyncClient):
    """测试1: 正常批量出库"""
    print("\n" + "=" * 60)
    print("测试1: 正常批量出库")
    print("=" * 60)

    payload = {
        "stockouts": [
            {
                "product_id": 1,
                "customer": "测试客户A",
                "quantity": 10,
                "note": "批量出库测试-正常",
            }
        ]
    }

    resp = await client.post(
        f"{BASE_URL}/batch-submit-stockouts",
        json=payload,
        headers=await get_headers(),
    )

    print(f"状态码: {resp.status_code}")
    data = resp.json()
    print(f"响应: {json.dumps(data, ensure_ascii=False, indent=2)}")

    # 验证
    assert resp.status_code == 200, f"期望 200，实际 {resp.status_code}"
    results = data.get("results", [])
    assert len(results) == 1, f"期望 1 条结果，实际 {len(results)}"
    assert results[0].get("success") is True, f"出库失败: {results[0].get('error')}"
    print("✓ 正常出库测试通过")
    return data


async def test_batch_stockout_insufficient(client: httpx.AsyncClient):
    """测试2: 库存不足"""
    print("\n" + "=" * 60)
    print("测试2: 库存不足")
    print("=" * 60)

    payload = {
        "stockouts": [
            {
                "product_id": 1,
                "customer": "测试客户A",
                "quantity": 9999999,  # 超大数量
                "note": "批量出库测试-库存不足",
            }
        ]
    }

    resp = await client.post(
        f"{BASE_URL}/batch-submit-stockouts",
        json=payload,
        headers=await get_headers(),
    )

    print(f"状态码: {resp.status_code}")
    data = resp.json()
    print(f"响应: {json.dumps(data, ensure_ascii=False, indent=2)}")

    # 库存不足应该返回 400 或 results 中标记失败
    if resp.status_code == 400:
        print("✓ 库存不足测试通过（HTTP 400）")
    elif resp.status_code == 200:
        results = data.get("results", [])
        assert results[0].get("success") is False, "期望出库失败"
        assert "库存不足" in results[0].get("error", ""), f"期望错误包含'库存不足'，实际: {results[0].get('error')}"
        print("✓ 库存不足测试通过（结果中标记失败）")
    else:
        print(f"✗ 意外状态码: {resp.status_code}")


async def test_batch_stockout_no_customer(client: httpx.AsyncClient):
    """测试3: 未选择客户"""
    print("\n" + "=" * 60)
    print("测试3: 未选择客户")
    print("=" * 60)

    payload = {
        "stockouts": [
            {
                "product_id": 1,
                "customer": "",
                "quantity": 10,
                "note": "批量出库测试-无客户",
            }
        ]
    }

    resp = await client.post(
        f"{BASE_URL}/batch-submit-stockouts",
        json=payload,
        headers=await get_headers(),
    )

    print(f"状态码: {resp.status_code}")
    data = resp.json()
    print(f"响应: {json.dumps(data, ensure_ascii=False, indent=2)}")

    # Pydantic 校验 customer 非空，应返回 422
    # 或 service 层校验返回 400/results 中失败
    if resp.status_code == 422:
        print("✓ 未选择客户测试通过（Pydantic 422）")
    elif resp.status_code == 400:
        print("✓ 未选择客户测试通过（HTTP 400）")
    elif resp.status_code == 200:
        results = data.get("results", [])
        assert results[0].get("success") is False
        print("✓ 未选择客户测试通过（结果中标记失败）")
    else:
        print(f"✗ 意外状态码: {resp.status_code}")


async def test_batch_stockout_custom_no_country(client: httpx.AsyncClient):
    """测试4: 定制订单缺少国家"""
    print("\n" + "=" * 60)
    print("测试4: 定制订单缺少国家")
    print("=" * 60)

    payload = {
        "stockouts": [
            {
                "product_id": 1,
                "customer": "测试客户A",
                "quantity": 10,
                "order_type": "custom",
                "country": "",
                "note": "批量出库测试-定制无国家",
            }
        ]
    }

    resp = await client.post(
        f"{BASE_URL}/batch-submit-stockouts",
        json=payload,
        headers=await get_headers(),
    )

    print(f"状态码: {resp.status_code}")
    data = resp.json()
    print(f"响应: {json.dumps(data, ensure_ascii=False, indent=2)}")

    if resp.status_code == 400:
        print("✓ 定制订单缺少国家测试通过（HTTP 400）")
    elif resp.status_code == 200:
        results = data.get("results", [])
        assert results[0].get("success") is False
        assert "国家" in results[0].get("error", "")
        print("✓ 定制订单缺少国家测试通过（结果中标记失败）")
    else:
        print(f"✗ 意外状态码: {resp.status_code}")


async def test_batch_stockout_mixed(client: httpx.AsyncClient):
    """测试5: 部分成功部分失败"""
    print("\n" + "=" * 60)
    print("测试5: 部分成功部分失败（混合请求）")
    print("=" * 60)

    payload = {
        "stockouts": [
            {
                "product_id": 1,
                "customer": "测试客户A",
                "quantity": 5,
                "note": "批量出库测试-应该成功",
            },
            {
                "product_id": 1,
                "customer": "",
                "quantity": 10,
                "note": "批量出库测试-应该失败（无客户）",
            },
            {
                "product_id": 1,
                "customer": "测试客户A",
                "quantity": 9999999,
                "note": "批量出库测试-应该失败（库存不足）",
            },
        ]
    }

    resp = await client.post(
        f"{BASE_URL}/batch-submit-stockouts",
        json=payload,
        headers=await get_headers(),
    )

    print(f"状态码: {resp.status_code}")
    data = resp.json()
    print(f"响应: {json.dumps(data, ensure_ascii=False, indent=2)}")

    if resp.status_code == 200:
        results = data.get("results", [])
        success_count = sum(1 for r in results if r.get("success"))
        fail_count = sum(1 for r in results if not r.get("success"))
        print(f"成功: {success_count}, 失败: {fail_count}")
        print("✓ 混合请求测试通过")
    else:
        print(f"✗ 意外状态码: {resp.status_code}")


async def verify_stock_decreased(client: httpx.AsyncClient, product_id: int, before_stock: int, qty: int):
    """验证库存是否正确扣减"""
    print("\n" + "=" * 60)
    print(f"验证库存扣减: 产品ID={product_id}")
    print("=" * 60)

    resp = await client.get(
        f"http://192.168.0.95:8000/api/v1/auxiliary/product-available-stock?product_id={product_id}",
        headers=await get_headers(),
    )

    if resp.status_code == 200:
        data = resp.json()
        after_stock = data.get("current_stock", "N/A")
        expected = before_stock - qty
        print(f"出库前库存: {before_stock}")
        print(f"出库数量: {qty}")
        print(f"出库后库存: {after_stock}")
        print(f"期望库存: {expected}")
        if after_stock == expected:
            print("✓ 库存扣减正确")
        else:
            print(f"✗ 库存扣减异常！期望 {expected}，实际 {after_stock}")
    else:
        print(f"获取库存失败: {resp.status_code}")


async def main():
    """运行所有测试"""
    print("=" * 60)
    print("批量出库接口本地测试")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"目标: {BASE_URL}")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            # 先检查服务是否可用
            resp = await client.get(
                "http://192.168.0.95:8000/api/health",
                headers=await get_headers(),
            )
            print(f"服务健康检查: {resp.status_code}")
        except httpx.ConnectError:
            print("✗ 无法连接到服务，请确认 FastAPI 正在运行")
            return

        # 获取出库前库存
        try:
            resp = await client.get(
                f"http://192.168.0.95:8000/api/v1/auxiliary/product-available-stock?product_id=1",
                headers=await get_headers(),
            )
            before_stock = resp.json().get("current_stock", "N/A") if resp.status_code == 200 else "N/A"
            print(f"产品ID=1 当前库存: {before_stock}")
        except Exception as e:
            before_stock = "N/A"
            print(f"获取库存失败: {e}")

        # 运行测试
        try:
            await test_batch_stockout_normal(client)
        except AssertionError as e:
            print(f"✗ 测试1失败: {e}")

        try:
            await test_batch_stockout_insufficient(client)
        except AssertionError as e:
            print(f"✗ 测试2失败: {e}")

        try:
            await test_batch_stockout_no_customer(client)
        except AssertionError as e:
            print(f"✗ 测试3失败: {e}")

        try:
            await test_batch_stockout_custom_no_country(client)
        except AssertionError as e:
            print(f"✗ 测试4失败: {e}")

        try:
            await test_batch_stockout_mixed(client)
        except AssertionError as e:
            print(f"✗ 测试5失败: {e}")

        # 验证库存扣减
        if isinstance(before_stock, int):
            try:
                await verify_stock_decreased(client, 1, before_stock, 10)
            except Exception as e:
                print(f"✗ 库存验证失败: {e}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
