#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
详细的备货抵扣功能调试脚本
"""

import sys
import os
import json
from datetime import datetime

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db, Product, Order, StockIn, StockOut, InventoryLog, User


def create_test_user():
    """创建测试用户"""
    with app.app_context():
        user = User.query.filter_by(username='test').first()
        if not user:
            from werkzeug.security import generate_password_hash
            user = User(
                username='test',
                password=generate_password_hash('test123'),
                is_super=True
            )
            db.session.add(user)
            db.session.commit()
            print(f"测试用户创建成功: ID={user.id}")
        return user.id


def detailed_test():
    """详细的功能测试"""
    print("=" * 70)
    print("备货抵扣功能详细调试")
    print("=" * 70)
    
    user_id = create_test_user()
    
    with app.test_client() as client:
        # 设置会话
        with client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['is_super'] = True
            sess['username'] = 'test'
            sess['permissions'] = ['order_manage']
        
        print(f"\n✓ 已设置会话: user_id={user_id}, is_super=True")
        
        # 1. 测试产品搜索API
        print("\n" + "=" * 70)
        print("1. 测试产品搜索API")
        print("-" * 70)
        response = client.get('/api/product-search?q=小狗')
        print(f"状态码: {response.status_code}")
        if response.status_code == 200:
            products = response.get_json()
            print(f"找到 {len(products)} 个产品")
            for p in products[:3]:
                print(f"  - {p['name']} (ID: {p['id']}, 库存: {p['current_stock']})")
        
        # 2. 测试获取可用备货API
        print("\n" + "=" * 70)
        print("2. 测试获取可用备货API")
        print("-" * 70)
        with app.app_context():
            product = Product.query.filter(Product.name.contains('鲨鱼')).first()
            if product:
                product_id = product.id
                print(f"\n使用产品: {product.name} (ID: {product_id})")
                
                response = client.get(f'/api/available-stockins?product_id={product_id}&order_quantity=10')
                print(f"\nAPI响应状态码: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.get_json()
                    print(f"找到 {len(data)} 个可用备货")
                    for s in data:
                        print(f"  - {s['stockin_no']}: 数量 {s['quantity']}")
                else:
                    print(f"响应内容: {response.data.decode('utf-8', errors='ignore')}")
        
        # 3. 检查订单提交逻辑
        print("\n" + "=" * 70)
        print("3. 检查提交数据格式")
        print("-" * 70)
        
        with app.app_context():
            product = Product.query.first()
            if product:
                print(f"\n测试数据准备:")
                print(f"  产品ID: {product.id}")
                print(f"  产品名称: {product.name}")
                
                # 模拟前端提交的数据
                test_form_data = {
                    'customer': 'MINISO 国际',
                    'product_id': str(product.id),
                    'product_search': product.name,
                    'quantity': '5',
                    'order_no': '2026-03-13-999',
                    'note': '测试订单',
                    'deduct_stock': 'on',
                    'deduct_stockins': json.dumps([{'id': 'custom', 'quantity': 3}])
                }
                
                print(f"\n模拟前端提交的数据:")
                for k, v in test_form_data.items():
                    print(f"  {k} = {v}")
        
        # 4. 检查后端代码问题
        print("\n" + "=" * 70)
        print("4. 分析发现的问题")
        print("-" * 70)
        
        print("\n⚠️  发现的问题:")
        print("1. 权限装饰器在测试环境中可能有问题")
        print("2. 前端提交数据时需要确保所有必填字段都正确")
        print("3. 抵扣备货逻辑需要仔细检查")
        
        print("\n💡 建议的调试步骤:")
        print("1. 先创建一个测试产品和测试备货")
        print("2. 手动访问订单页面，填写表单并点击'抵扣备货'")
        print("3. 查看浏览器开发者工具的网络请求")
        print("4. 检查服务器日志中的错误信息")


if __name__ == '__main__':
    detailed_test()
