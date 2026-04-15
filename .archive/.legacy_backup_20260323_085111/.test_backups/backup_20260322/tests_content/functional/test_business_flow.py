"""
功能测试 - 业务流程测试
测试完整的业务场景,包括产品管理、订单处理、库存管理等
"""
import pytest
from datetime import datetime
from app import app, db
from app.models import Product, Order, StockIn, StockOut, InventoryLog


@pytest.mark.functional
class TestProductManagement:
    """产品管理功能测试"""
    
    def test_product_lifecycle(self, test_app):
        """测试产品完整生命周期:创建->查询->更新->删除"""
        with test_app.app_context():
            # 1. 创建产品
            product = Product(
                name='生命周期测试产品',
                barcode='6901111111111',
                initial_stock=100,
                current_stock=100
            )
            db.session.add(product)
            db.session.commit()
            
            product_id = product.id
            assert product_id is not None
            
            # 2. 查询产品
            found_product = Product.query.get(product_id)
            assert found_product is not None
            assert found_product.name == '生命周期测试产品'
            
            # 3. 更新产品
            found_product.name = '更新后的产品名'
            found_product.current_stock = 150
            db.session.commit()
            
            updated_product = Product.query.get(product_id)
            assert updated_product.name == '更新后的产品名'
            assert updated_product.current_stock == 150
            
            # 4. 删除产品
            db.session.delete(updated_product)
            db.session.commit()
            
            deleted_product = Product.query.get(product_id)
            assert deleted_product is None
    
    def test_product_search_by_name(self, test_app):
        """测试按名称搜索产品"""
        with test_app.app_context():
            # 创建多个产品
            products = [
                Product(name=f'搜索测试产品{i}', barcode=f'690222222222{i}')
                for i in range(1, 6)
            ]
            db.session.add_all(products)
            db.session.commit()
            
            # 搜索产品
            search_results = Product.query.filter(
                Product.name.like('%搜索测试%')
            ).all()
            
            assert len(search_results) == 5
    
    def test_product_stock_management(self, test_app):
        """测试产品库存管理"""
        with test_app.app_context():
            product = Product(
                name='库存管理测试',
                initial_stock=100,
                current_stock=100
            )
            db.session.add(product)
            db.session.commit()
            
            # 增加库存
            product.current_stock += 50
            db.session.commit()
            assert product.current_stock == 150
            
            # 减少库存
            product.current_stock -= 30
            db.session.commit()
            assert product.current_stock == 120


@pytest.mark.functional
class TestOrderProcessing:
    """订单处理功能测试"""
    
    def test_order_creation_flow(self, test_app):
        """测试订单创建流程"""
        with test_app.app_context():
            # 1. 创建产品
            product = Product(name='订单流程产品', current_stock=100)
            db.session.add(product)
            db.session.commit()
            
            # 2. 创建订单
            order = Order(
                order_no=f'ORD-{datetime.now().strftime("%Y%m%d%H%M%S")}',
                customer='订单流程客户',
                product_id=product.id,
                quantity=10,
                status='待备货'
            )
            db.session.add(order)
            db.session.commit()
            
            # 3. 验证订单创建成功
            assert order.id is not None
            assert order.status == '待备货'
            assert order.product.name == '订单流程产品'
    
    def test_order_status_transition(self, test_app):
        """测试订单状态转换"""
        with test_app.app_context():
            product = Product(name='状态转换产品')
            db.session.add(product)
            db.session.commit()
            
            order = Order(
                order_no='ORD-STATUS-001',
                customer='状态客户',
                product_id=product.id,
                quantity=10,
                status='待备货'
            )
            db.session.add(order)
            db.session.commit()
            
            # 状态转换: 待备货 -> 部分备货
            order.status = '部分备货'
            db.session.commit()
            assert order.status == '部分备货'
            
            # 状态转换: 部分备货 -> 已备货
            order.status = '已备货'
            db.session.commit()
            assert order.status == '已备货'
            
            # 状态转换: 已备货 -> 待出货
            order.status = '待出货'
            db.session.commit()
            assert order.status == '待出货'
            
            # 状态转换: 待出货 -> 已出货
            order.status = '已出货'
            db.session.commit()
            assert order.status == '已出货'
    
    def test_order_cancellation(self, test_app):
        """测试订单取消"""
        with test_app.app_context():
            product = Product(name='取消订单产品')
            db.session.add(product)
            db.session.commit()
            
            order = Order(
                order_no='ORD-CANCEL-001',
                customer='取消客户',
                product_id=product.id,
                quantity=10,
                status='待备货'
            )
            db.session.add(order)
            db.session.commit()
            
            # 取消订单
            order.status = '已取消'
            db.session.commit()
            
            assert order.status == '已取消'


@pytest.mark.functional
class TestStockManagement:
    """库存管理功能测试"""
    
    def test_stockin_flow(self, test_app):
        """测试入库流程"""
        with test_app.app_context():
            # 1. 创建产品
            product = Product(name='入库流程产品', current_stock=100)
            db.session.add(product)
            db.session.commit()
            
            initial_stock = product.current_stock
            
            # 2. 创建入库记录
            stockin = StockIn(
                stockin_no=f'SI-{datetime.now().strftime("%Y%m%d%H%M%S")}',
                customer='入库客户',
                product_id=product.id,
                quantity=50
            )
            db.session.add(stockin)
            db.session.commit()
            
            # 3. 更新库存
            product.current_stock += stockin.quantity
            db.session.commit()
            
            # 4. 验证库存更新
            assert product.current_stock == initial_stock + 50
            
            # 5. 创建库存日志
            log = InventoryLog(
                product_id=product.id,
                change_type='备货',
                change_quantity=50,
                related_id=stockin.stockin_no,
                customer='入库客户'
            )
            db.session.add(log)
            db.session.commit()
            
            assert log.id is not None
    
    def test_stockout_flow(self, test_app):
        """测试出库流程"""
        with test_app.app_context():
            # 1. 创建产品
            product = Product(name='出库流程产品', current_stock=100)
            db.session.add(product)
            db.session.commit()
            
            initial_stock = product.current_stock
            
            # 2. 创建出库记录
            stockout = StockOut(
                stockout_no=f'SO-{datetime.now().strftime("%Y%m%d%H%M%S")}',
                product_id=product.id,
                quantity=30,
                customer='出库客户'
            )
            db.session.add(stockout)
            db.session.commit()
            
            # 3. 更新库存
            product.current_stock -= stockout.quantity
            db.session.commit()
            
            # 4. 验证库存更新
            assert product.current_stock == initial_stock - 30
            
            # 5. 创建库存日志
            log = InventoryLog(
                product_id=product.id,
                change_type='出货',
                change_quantity=-30,
                related_id=stockout.stockout_no,
                customer='出库客户'
            )
            db.session.add(log)
            db.session.commit()
            
            assert log.id is not None
    
    def test_stock_calculation(self, test_app):
        """测试库存计算正确性"""
        with test_app.app_context():
            # 创建产品,初始库存100
            product = Product(name='库存计算产品', initial_stock=100, current_stock=100)
            db.session.add(product)
            db.session.commit()
            
            # 入库50
            product.current_stock += 50
            db.session.commit()
            assert product.current_stock == 150
            
            # 出库30
            product.current_stock -= 30
            db.session.commit()
            assert product.current_stock == 120
            
            # 再入库20
            product.current_stock += 20
            db.session.commit()
            assert product.current_stock == 140
            
            # 再出库40
            product.current_stock -= 40
            db.session.commit()
            assert product.current_stock == 100


@pytest.mark.functional
class TestInventoryLog:
    """库存日志功能测试"""
    
    def test_inventory_log_creation(self, test_app):
        """测试库存日志创建"""
        with test_app.app_context():
            product = Product(name='日志测试产品')
            db.session.add(product)
            db.session.commit()
            
            # 创建库存日志
            log = InventoryLog(
                product_id=product.id,
                change_type='初始库存',
                change_quantity=100,
                related_id='INIT-001',
                note='初始库存设置'
            )
            db.session.add(log)
            db.session.commit()
            
            assert log.id is not None
            assert log.change_type == '初始库存'
            assert log.change_quantity == 100
    
    def test_inventory_log_history(self, test_app):
        """测试库存日志历史记录"""
        with test_app.app_context():
            product = Product(name='历史记录产品')
            db.session.add(product)
            db.session.commit()
            
            # 创建多条日志
            logs = [
                InventoryLog(
                    product_id=product.id,
                    change_type='备货',
                    change_quantity=50,
                    related_id=f'SI-{i}'
                )
                for i in range(1, 6)
            ]
            db.session.add_all(logs)
            db.session.commit()
            
            # 查询日志历史
            history = InventoryLog.query.filter_by(product_id=product.id).all()
            assert len(history) == 5
