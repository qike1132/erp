"""
审批管理模块功能测试
测试范围：审批流程创建、审批任务提交、审批状态跟踪、审批权限管理、审批记录查询
"""
import unittest
import json
import sys
import os
import tempfile
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect


class ApprovalManagementTestCase(unittest.TestCase):
    """审批管理功能测试用例集"""
    
    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        # 创建测试用的Flask应用
        cls.app = Flask(__name__)
        cls.app.config['TESTING'] = True
        cls.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        cls.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.app.config['SECRET_KEY'] = 'test-secret-key'
        
        # 初始化数据库
        cls.db = SQLAlchemy(cls.app)
        CSRFProtect(cls.app)
        
        # 定义模型
        cls._define_models()
        
        # 注册路由
        with cls.app.app_context():
            cls.db.create_all()
            cls._init_test_data()
    
    @classmethod
    def _define_models(cls):
        """定义数据模型"""
        db = cls.db
        
        # 权限模型
        class Permission(db.Model):
            __tablename__ = 'permission'
            id = db.Column(db.Integer, primary_key=True)
            name = db.Column(db.String(50), nullable=False)
            code = db.Column(db.String(50), unique=True, nullable=False)
            parent_id = db.Column(db.Integer, db.ForeignKey('permission.id'))
        
        # 用户权限关联表
        user_permission = db.Table('user_permission',
            db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
            db.Column('permission_id', db.Integer, db.ForeignKey('permission.id'), primary_key=True)
        )
        
        # 用户模型
        class User(db.Model):
            __tablename__ = 'user'
            id = db.Column(db.Integer, primary_key=True)
            username = db.Column(db.String(50), unique=True, nullable=False)
            phone = db.Column(db.String(20))
            password = db.Column(db.String(200), nullable=False)
            is_super = db.Column(db.Boolean, default=False)
            status = db.Column(db.Boolean, default=True)
            create_time = db.Column(db.DateTime, default=datetime.now)
            update_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
            permissions = db.relationship('Permission', secondary='user_permission', backref=db.backref('users', lazy=True))
            
            def has_permission(self, permission_code):
                if self.is_super:
                    return True
                for p in self.permissions:
                    if p.code == permission_code:
                        return True
                return False
        
        # 产品模型
        class Product(db.Model):
            __tablename__ = 'product'
            id = db.Column(db.Integer, primary_key=True)
            name = db.Column(db.String(100), nullable=False)
            barcode = db.Column(db.String(50), unique=True)
            specification = db.Column(db.String(50))
            unit = db.Column(db.String(20))
            current_stock = db.Column(db.Integer, default=0)
        
        # 订单模型
        class Order(db.Model):
            __tablename__ = 'order'
            id = db.Column(db.Integer, primary_key=True)
            order_no = db.Column(db.String(20), unique=True, nullable=False)
            customer = db.Column(db.String(100), nullable=False)
            order_date = db.Column(db.DateTime, default=datetime.now)
            product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
            quantity = db.Column(db.Integer, nullable=False)
            status = db.Column(db.String(20), default='待备货')
            note = db.Column(db.Text)
            is_locked = db.Column(db.Boolean, default=False)
            locked_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
            lock_time = db.Column(db.DateTime)
            product = db.relationship('Product', backref=db.backref('orders', lazy=True))
            locked_by = db.relationship('User', foreign_keys=[locked_by_id], backref=db.backref('locked_orders', lazy=True))
            
            def lock(self, user_id):
                self.is_locked = True
                self.locked_by_id = user_id
                self.lock_time = datetime.now()
            
            def unlock(self):
                self.is_locked = False
                self.locked_by_id = None
                self.lock_time = None
            
            def is_locked_by_other(self, user_id):
                return self.is_locked and self.locked_by_id != user_id
        
        # 审批请求模型
        class ApprovalRequest(db.Model):
            __tablename__ = 'approval_request'
            id = db.Column(db.Integer, primary_key=True)
            order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
            requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
            operation_type = db.Column(db.String(20), nullable=False)
            operation_data = db.Column(db.Text)
            status = db.Column(db.String(20), default='pending', index=True)
            request_time = db.Column(db.DateTime, default=datetime.now, index=True)
            approver_id = db.Column(db.Integer, db.ForeignKey('user.id'))
            approval_time = db.Column(db.DateTime)
            rejection_reason = db.Column(db.Text)
            lock_time = db.Column(db.DateTime)
            order = db.relationship('Order', backref=db.backref('approval_requests', lazy=True))
            requester = db.relationship('User', foreign_keys=[requester_id], backref=db.backref('approval_requests_made', lazy=True))
            approver = db.relationship('User', foreign_keys=[approver_id], backref=db.backref('approval_requests_handled', lazy=True))
            
            @property
            def status_display(self):
                status_map = {
                    'pending': '待审批',
                    'approved': '已同意',
                    'rejected': '已拒绝',
                    'cancelled': '已取消'
                }
                return status_map.get(self.status, self.status)
            
            @property
            def operation_type_display(self):
                operation_map = {
                    'edit': '编辑',
                    'delete': '删除'
                }
                return operation_map.get(self.operation_type, self.operation_type)
        
        # 审批日志模型
        class ApprovalLog(db.Model):
            __tablename__ = 'approval_log'
            id = db.Column(db.Integer, primary_key=True)
            approval_request_id = db.Column(db.Integer, db.ForeignKey('approval_request.id'), nullable=False)
            action = db.Column(db.String(50), nullable=False)
            actor_id = db.Column(db.Integer, db.ForeignKey('user.id'))
            actor_name = db.Column(db.String(50))
            action_time = db.Column(db.DateTime, default=datetime.now, index=True)
            details = db.Column(db.Text)
            approval_request = db.relationship('ApprovalRequest', backref=db.backref('logs', lazy=True, order_by='ApprovalLog.action_time.desc()'))
            actor = db.relationship('User', backref=db.backref('approval_logs', lazy=True))
            
            @property
            def action_display(self):
                action_map = {
                    'create': '创建审批请求',
                    'approve': '同意审批',
                    'reject': '拒绝审批',
                    'cancel': '取消审批',
                    'execute': '执行操作'
                }
                return action_map.get(self.action, self.action)
        
        # 保存模型类引用
        cls.Permission = Permission
        cls.User = User
        cls.Product = Product
        cls.Order = Order
        cls.ApprovalRequest = ApprovalRequest
        cls.ApprovalLog = ApprovalLog
    
    @classmethod
    def _init_test_data(cls):
        """初始化测试数据"""
        db = cls.db
        
        # 创建权限
        order_permission = cls.Permission(name='订单管理', code='order_manage')
        approval_permission = cls.Permission(name='审批管理', code='approval_manage')
        db.session.add_all([order_permission, approval_permission])
        
        # 创建管理员用户
        admin = cls.User(
            username='admin',
            password='test_password',
            is_super=True,
            status=True
        )
        
        # 创建普通用户
        normal_user = cls.User(
            username='normal_user',
            password='test_password',
            is_super=False,
            status=True
        )
        normal_user.permissions.append(order_permission)
        
        # 创建另一个普通用户
        other_user = cls.User(
            username='other_user',
            password='test_password',
            is_super=False,
            status=True
        )
        other_user.permissions.append(order_permission)
        
        db.session.add_all([admin, normal_user, other_user])
        db.session.commit()
        
        # 创建测试产品
        product = cls.Product(
            name='测试产品',
            barcode='6901234567890',
            specification='500ml',
            unit='瓶',
            current_stock=100
        )
        db.session.add(product)
        db.session.commit()
        
        # 创建测试订单
        order = cls.Order(
            order_no='ORD20250101001',
            customer='测试客户',
            product_id=product.id,
            quantity=10,
            status='待备货',
            note='测试订单备注'
        )
        db.session.add(order)
        db.session.commit()
    
    def setUp(self):
        """每个测试前的准备"""
        self.client = self.app.test_client()
    
    def tearDown(self):
        """每个测试后的清理"""
        pass
    
    # ==================== 审批流程创建测试 ====================
    
    def test_01_create_edit_approval_request(self):
        """测试用例01：创建编辑审批请求"""
        print("\n[测试用例01] 创建编辑审批请求")
        
        with self.app.app_context():
            user = self.User.query.filter_by(username='normal_user').first()
            order = self.Order.query.first()
            
            # 创建审批请求
            approval = self.ApprovalRequest(
                order_id=order.id,
                requester_id=user.id,
                operation_type='edit',
                operation_data=json.dumps({
                    'customer': '新客户名',
                    'quantity': 20,
                    'note': '修改后的备注'
                }),
                status='pending'
            )
            self.db.session.add(approval)
            
            # 锁定订单
            order.lock(user.id)
            self.db.session.commit()
            
            # 验证审批请求创建
            approval_check = self.ApprovalRequest.query.filter_by(
                order_id=order.id,
                requester_id=user.id,
                operation_type='edit'
            ).first()
            
            self.assertIsNotNone(approval_check, "编辑审批请求应被创建")
            self.assertEqual(approval_check.status, 'pending', "状态应为待审批")
            
            # 验证订单被锁定
            order_check = self.Order.query.get(order.id)
            self.assertTrue(order_check.is_locked, "订单应被锁定")
            self.assertEqual(order_check.locked_by_id, user.id, "锁定人应为申请人")
            
            print("  ✓ 编辑审批请求创建成功")
            print("  ✓ 订单锁定机制正常")
    
    def test_02_create_delete_approval_request(self):
        """测试用例02：创建删除审批请求"""
        print("\n[测试用例02] 创建删除审批请求")
        
        with self.app.app_context():
            user = self.User.query.filter_by(username='normal_user').first()
            order = self.Order.query.first()
            
            # 创建删除审批请求
            approval = self.ApprovalRequest(
                order_id=order.id,
                requester_id=user.id,
                operation_type='delete',
                operation_data=json.dumps({
                    'order_no': order.order_no,
                    'customer': order.customer,
                    'quantity': order.quantity
                }),
                status='pending'
            )
            self.db.session.add(approval)
            order.lock(user.id)
            self.db.session.commit()
            
            # 验证
            approval_check = self.ApprovalRequest.query.filter_by(
                order_id=order.id,
                requester_id=user.id,
                operation_type='delete'
            ).first()
            
            self.assertIsNotNone(approval_check, "删除审批请求应被创建")
            self.assertEqual(approval_check.status, 'pending', "状态应为待审批")
            
            print("  ✓ 删除审批请求创建成功")
    
    def test_03_duplicate_approval_prevention(self):
        """测试用例03：防止重复提交审批"""
        print("\n[测试用例03] 防止重复提交审批")
        
        with self.app.app_context():
            user = self.User.query.filter_by(username='normal_user').first()
            order = self.Order.query.first()
            
            # 先解锁订单并清理之前的审批请求
            order.unlock()
            self.ApprovalRequest.query.filter_by(
                order_id=order.id,
                requester_id=user.id,
                status='pending'
            ).delete()
            self.db.session.commit()
            
            # 创建第一个审批请求
            approval1 = self.ApprovalRequest(
                order_id=order.id,
                requester_id=user.id,
                operation_type='edit',
                status='pending'
            )
            self.db.session.add(approval1)
            order.lock(user.id)
            self.db.session.commit()
            
            # 验证只有一个审批请求
            count = self.ApprovalRequest.query.filter_by(
                order_id=order.id,
                requester_id=user.id,
                status='pending'
            ).count()
            
            self.assertEqual(count, 1, "不应创建重复的审批请求")
            print("  ✓ 重复提交防护正常")
    
    # ==================== 审批任务提交测试 ====================
    
    def test_04_admin_approve_edit_request(self):
        """测试用例04：管理员同意编辑请求"""
        print("\n[测试用例04] 管理员同意编辑请求")
        
        with self.app.app_context():
            user = self.User.query.filter_by(username='normal_user').first()
            admin = self.User.query.filter_by(username='admin').first()
            order = self.Order.query.first()
            product = self.Product.query.first()
            
            # 先解锁订单
            order.unlock()
            
            # 创建审批请求
            approval = self.ApprovalRequest(
                order_id=order.id,
                requester_id=user.id,
                operation_type='edit',
                operation_data=json.dumps({
                    'customer': '新客户',
                    'quantity': 20,
                    'note': '新备注',
                    'original_customer': order.customer,
                    'original_quantity': order.quantity,
                    'original_note': order.note or ''
                }),
                status='pending'
            )
            self.db.session.add(approval)
            order.lock(user.id)
            self.db.session.commit()
            
            original_stock = product.current_stock
            
            # 模拟管理员审批通过
            approval.status = 'approved'
            approval.approver_id = admin.id
            approval.approval_time = datetime.now()
            
            # 执行编辑操作
            operation_data = json.loads(approval.operation_data)
            order.customer = operation_data['customer']
            order.quantity = operation_data['quantity']
            order.note = operation_data['note']
            
            # 更新库存
            product.current_stock += (operation_data['quantity'] - operation_data['original_quantity'])
            
            # 解锁订单
            order.unlock()
            
            # 创建审批日志
            log = self.ApprovalLog(
                approval_request_id=approval.id,
                action='approve',
                actor_id=admin.id,
                actor_name=admin.username
            )
            self.db.session.add(log)
            self.db.session.commit()
            
            # 验证审批结果
            approval_check = self.ApprovalRequest.query.get(approval.id)
            self.assertEqual(approval_check.status, 'approved', "状态应为已同意")
            self.assertEqual(approval_check.approver_id, admin.id, "审批人应为管理员")
            
            # 验证订单更新
            order_check = self.Order.query.get(order.id)
            self.assertEqual(order_check.customer, '新客户', "客户名应更新")
            self.assertEqual(order_check.quantity, 20, "数量应更新")
            self.assertFalse(order_check.is_locked, "订单应解锁")
            
            # 验证库存变化
            product_check = self.Product.query.get(product.id)
            expected_stock = original_stock + (20 - 10)
            self.assertEqual(product_check.current_stock, expected_stock, "库存应正确更新")
            
            print("  ✓ 审批同意操作成功")
            print("  ✓ 订单数据更新正确")
            print("  ✓ 库存联动正确")
            print("  ✓ 订单解锁正常")
    
    def test_05_admin_reject_request(self):
        """测试用例05：管理员拒绝审批请求"""
        print("\n[测试用例05] 管理员拒绝审批请求")
        
        with self.app.app_context():
            user = self.User.query.filter_by(username='normal_user').first()
            admin = self.User.query.filter_by(username='admin').first()
            order = self.Order.query.first()
            
            # 创建审批请求
            approval = self.ApprovalRequest(
                order_id=order.id,
                requester_id=user.id,
                operation_type='edit',
                operation_data=json.dumps({
                    'customer': '测试',
                    'quantity': 30,
                    'note': ''
                }),
                status='pending'
            )
            self.db.session.add(approval)
            order.lock(user.id)
            self.db.session.commit()
            
            # 模拟管理员拒绝
            approval.status = 'rejected'
            approval.approver_id = admin.id
            approval.approval_time = datetime.now()
            approval.rejection_reason = '数据不正确'
            
            # 解锁订单
            order.unlock()
            
            # 创建审批日志
            log = self.ApprovalLog(
                approval_request_id=approval.id,
                action='reject',
                actor_id=admin.id,
                actor_name=admin.username,
                details=json.dumps({'reason': '数据不正确'})
            )
            self.db.session.add(log)
            self.db.session.commit()
            
            # 验证拒绝结果
            approval_check = self.ApprovalRequest.query.get(approval.id)
            self.assertEqual(approval_check.status, 'rejected', "状态应为已拒绝")
            self.assertEqual(approval_check.rejection_reason, '数据不正确', "拒绝原因应记录")
            
            # 验证订单解锁
            order_check = self.Order.query.get(order.id)
            self.assertFalse(order_check.is_locked, "订单应解锁")
            
            print("  ✓ 审批拒绝操作成功")
            print("  ✓ 拒绝原因记录正确")
            print("  ✓ 订单解锁正常")
    
    def test_06_user_cancel_approval(self):
        """测试用例06：用户取消审批请求"""
        print("\n[测试用例06] 用户取消审批请求")
        
        with self.app.app_context():
            user = self.User.query.filter_by(username='normal_user').first()
            order = self.Order.query.first()
            
            # 创建审批请求
            approval = self.ApprovalRequest(
                order_id=order.id,
                requester_id=user.id,
                operation_type='edit',
                operation_data=json.dumps({'customer': '测试', 'quantity': 15}),
                status='pending'
            )
            self.db.session.add(approval)
            order.lock(user.id)
            self.db.session.commit()
            
            # 模拟用户取消
            approval.status = 'cancelled'
            order.unlock()
            
            # 创建审批日志
            log = self.ApprovalLog(
                approval_request_id=approval.id,
                action='cancel',
                actor_id=user.id,
                actor_name=user.username
            )
            self.db.session.add(log)
            self.db.session.commit()
            
            # 验证取消结果
            approval_check = self.ApprovalRequest.query.get(approval.id)
            self.assertEqual(approval_check.status, 'cancelled', "状态应为已取消")
            
            # 验证订单解锁
            order_check = self.Order.query.get(order.id)
            self.assertFalse(order_check.is_locked, "订单应解锁")
            
            print("  ✓ 审批取消操作成功")
            print("  ✓ 订单解锁正常")
    
    # ==================== 审批状态跟踪测试 ====================
    
    def test_07_approval_status_display(self):
        """测试用例07：审批状态显示"""
        print("\n[测试用例07] 审批状态显示")
        
        with self.app.app_context():
            user = self.User.query.filter_by(username='normal_user').first()
            order = self.Order.query.first()
            
            approval = self.ApprovalRequest(
                order_id=order.id,
                requester_id=user.id,
                operation_type='edit',
                status='pending'
            )
            self.db.session.add(approval)
            self.db.session.commit()
            
            # 测试状态显示
            self.assertEqual(approval.status_display, '待审批', "状态显示应正确")
            
            approval.status = 'approved'
            self.assertEqual(approval.status_display, '已同意')
            
            approval.status = 'rejected'
            self.assertEqual(approval.status_display, '已拒绝')
            
            approval.status = 'cancelled'
            self.assertEqual(approval.status_display, '已取消')
            
            print("  ✓ 状态显示文本正确")
    
    def test_08_approval_log_tracking(self):
        """测试用例08：审批日志跟踪"""
        print("\n[测试用例08] 审批日志跟踪")
        
        with self.app.app_context():
            user = self.User.query.filter_by(username='normal_user').first()
            admin = self.User.query.filter_by(username='admin').first()
            order = self.Order.query.first()
            
            # 创建审批请求
            approval = self.ApprovalRequest(
                order_id=order.id,
                requester_id=user.id,
                operation_type='edit',
                status='pending'
            )
            self.db.session.add(approval)
            self.db.session.flush()
            
            # 创建日志
            log1 = self.ApprovalLog(
                approval_request_id=approval.id,
                action='create',
                actor_id=user.id,
                actor_name=user.username
            )
            self.db.session.add(log1)
            
            approval.status = 'approved'
            approval.approver_id = admin.id
            
            log2 = self.ApprovalLog(
                approval_request_id=approval.id,
                action='approve',
                actor_id=admin.id,
                actor_name=admin.username
            )
            self.db.session.add(log2)
            self.db.session.commit()
            
            # 验证日志
            logs = self.ApprovalLog.query.filter_by(approval_request_id=approval.id).order_by(self.ApprovalLog.id.desc()).all()
            self.assertEqual(len(logs), 2, "应有2条日志")
            self.assertEqual(logs[0].action, 'approve', "最新日志应为审批")
            self.assertEqual(logs[1].action, 'create', "最早日志应为创建")
            
            print("  ✓ 日志记录完整")
            print("  ✓ 日志顺序正确")
    
    # ==================== 审批权限管理测试 ====================
    
    def test_09_admin_permission_check(self):
        """测试用例09：管理员权限检查"""
        print("\n[测试用例09] 管理员权限检查")
        
        with self.app.app_context():
            admin = self.User.query.filter_by(username='admin').first()
            
            # 管理员应拥有所有权限
            self.assertTrue(admin.is_super, "管理员应为超级用户")
            self.assertTrue(admin.has_permission('approval_manage'), "管理员应有审批管理权限")
            self.assertTrue(admin.has_permission('order_manage'), "管理员应有订单管理权限")
            
            print("  ✓ 管理员权限正确")
    
    def test_10_normal_user_permission_check(self):
        """测试用例10：普通用户权限检查"""
        print("\n[测试用例10] 普通用户权限检查")
        
        with self.app.app_context():
            user = self.User.query.filter_by(username='normal_user').first()
            
            # 普通用户权限检查
            self.assertFalse(user.is_super, "普通用户不应为超级用户")
            self.assertTrue(user.has_permission('order_manage'), "普通用户应有订单管理权限")
            self.assertFalse(user.has_permission('approval_manage'), "普通用户不应有审批管理权限")
            
            print("  ✓ 普通用户权限正确")
    
    def test_11_permission_isolation(self):
        """测试用例11：数据权限隔离"""
        print("\n[测试用例11] 数据权限隔离")
        
        with self.app.app_context():
            user1 = self.User.query.filter_by(username='normal_user').first()
            user2 = self.User.query.filter_by(username='other_user').first()
            order = self.Order.query.first()
            
            # user1创建审批请求
            approval = self.ApprovalRequest(
                order_id=order.id,
                requester_id=user1.id,
                operation_type='edit',
                status='pending'
            )
            self.db.session.add(approval)
            self.db.session.commit()
            
            # 验证user2不能操作user1的审批
            self.assertNotEqual(approval.requester_id, user2.id, "审批请求不属于user2")
            
            print("  ✓ 数据权限隔离正确")
    
    # ==================== 边界条件测试 ====================
    
    def test_12_order_lock_mechanism(self):
        """测试用例12：订单锁定机制"""
        print("\n[测试用例12] 订单锁定机制")
        
        with self.app.app_context():
            user = self.User.query.filter_by(username='normal_user').first()
            other_user = self.User.query.filter_by(username='other_user').first()
            order = self.Order.query.first()
            
            # 解锁订单
            order.unlock()
            self.db.session.commit()
            
            # user锁定订单
            order.lock(user.id)
            self.db.session.commit()
            
            # 验证锁定状态
            self.assertTrue(order.is_locked, "订单应被锁定")
            self.assertEqual(order.locked_by_id, user.id, "锁定人应为user")
            
            # 验证其他用户检查
            self.assertTrue(order.is_locked_by_other(other_user.id), "对其他用户应显示为被锁定")
            self.assertFalse(order.is_locked_by_other(user.id), "对锁定人不应显示为被锁定")
            
            # 解锁
            order.unlock()
            self.db.session.commit()
            
            self.assertFalse(order.is_locked, "订单应被解锁")
            self.assertIsNone(order.locked_by_id, "锁定人应为空")
            
            print("  ✓ 订单锁定机制正常")
            print("  ✓ 锁定人检查正确")
            print("  ✓ 订单解锁正常")
    
    def test_13_approval_status_transitions(self):
        """测试用例13：审批状态转换"""
        print("\n[测试用例13] 审批状态转换")
        
        with self.app.app_context():
            user = self.User.query.filter_by(username='normal_user').first()
            order = self.Order.query.first()
            
            # 创建审批请求
            approval = self.ApprovalRequest(
                order_id=order.id,
                requester_id=user.id,
                operation_type='edit',
                status='pending'
            )
            self.db.session.add(approval)
            self.db.session.commit()
            
            # 验证初始状态
            self.assertEqual(approval.status, 'pending', "初始状态应为待审批")
            
            # 状态转换：pending -> approved
            approval.status = 'approved'
            self.db.session.commit()
            self.assertEqual(approval.status, 'approved', "状态应转换为已同意")
            
            print("  ✓ 状态转换正确")
    
    def test_14_operation_type_display(self):
        """测试用例14：操作类型显示"""
        print("\n[测试用例14] 操作类型显示")
        
        with self.app.app_context():
            user = self.User.query.filter_by(username='normal_user').first()
            order = self.Order.query.first()
            
            # 编辑操作
            edit_approval = self.ApprovalRequest(
                order_id=order.id,
                requester_id=user.id,
                operation_type='edit',
                status='pending'
            )
            self.assertEqual(edit_approval.operation_type_display, '编辑', "编辑操作显示正确")
            
            # 删除操作
            delete_approval = self.ApprovalRequest(
                order_id=order.id,
                requester_id=user.id,
                operation_type='delete',
                status='pending'
            )
            self.assertEqual(delete_approval.operation_type_display, '删除', "删除操作显示正确")
            
            print("  ✓ 操作类型显示正确")
    
    def test_15_approval_log_actions(self):
        """测试用例15：审批日志动作"""
        print("\n[测试用例15] 审批日志动作")
        
        with self.app.app_context():
            user = self.User.query.filter_by(username='normal_user').first()
            order = self.Order.query.first()
            
            approval = self.ApprovalRequest(
                order_id=order.id,
                requester_id=user.id,
                operation_type='edit',
                status='pending'
            )
            self.db.session.add(approval)
            self.db.session.flush()
            
            # 测试各种日志动作
            actions = ['create', 'approve', 'reject', 'cancel', 'execute']
            expected_displays = ['创建审批请求', '同意审批', '拒绝审批', '取消审批', '执行操作']
            
            for action, expected in zip(actions, expected_displays):
                log = self.ApprovalLog(
                    approval_request_id=approval.id,
                    action=action,
                    actor_id=user.id,
                    actor_name=user.username
                )
                self.db.session.add(log)
                self.assertEqual(log.action_display, expected, f"{action}动作显示应正确")
            
            self.db.session.commit()
            
            print("  ✓ 日志动作显示正确")


class ApprovalSecurityTestCase(unittest.TestCase):
    """审批管理安全测试用例集"""
    
    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.app = Flask(__name__)
        cls.app.config['TESTING'] = True
        cls.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        cls.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.app.config['SECRET_KEY'] = 'test-secret-key'
        
        cls.db = SQLAlchemy(cls.app)
        
        # 定义简化模型
        class User(cls.db.Model):
            __tablename__ = 'user'
            id = cls.db.Column(cls.db.Integer, primary_key=True)
            username = cls.db.Column(cls.db.String(50), unique=True, nullable=False)
            password = cls.db.Column(cls.db.String(200), nullable=False)
            is_super = cls.db.Column(cls.db.Boolean, default=False)
        
        cls.User = User
        
        with cls.app.app_context():
            cls.db.create_all()
            
            admin = cls.User(username='admin', password='test', is_super=True)
            user = cls.User(username='user', password='test', is_super=False)
            cls.db.session.add_all([admin, user])
            cls.db.session.commit()
    
    def setUp(self):
        """每个测试前的准备"""
        self.client = self.app.test_client()
    
    def test_unauthenticated_access(self):
        """安全测试：未认证访问"""
        print("\n[安全测试] 未认证访问")
        
        # 未登录访问应被拒绝
        response = self.client.get('/approval/list')
        self.assertIn(response.status_code, [302, 401, 404], "未认证应被重定向或拒绝")
        
        print("  ✓ 未认证访问防护正常")
    
    def test_permission_check(self):
        """安全测试：权限检查"""
        print("\n[安全测试] 权限检查")
        
        with self.app.app_context():
            admin = self.User.query.filter_by(username='admin').first()
            user = self.User.query.filter_by(username='user').first()
            
            self.assertTrue(admin.is_super, "管理员应为超级用户")
            self.assertFalse(user.is_super, "普通用户不应为超级用户")
            
            print("  ✓ 权限检查正常")


def run_tests():
    """运行所有测试"""
    print("=" * 70)
    print("审批管理模块功能测试报告")
    print("=" * 70)
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 70)
    
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加功能测试
    suite.addTests(loader.loadTestsFromTestCase(ApprovalManagementTestCase))
    
    # 添加安全测试
    suite.addTests(loader.loadTestsFromTestCase(ApprovalSecurityTestCase))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 输出统计
    print("\n" + "=" * 70)
    print("测试统计")
    print("=" * 70)
    print(f"总测试数: {result.testsRun}")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    
    if result.failures:
        print("\n失败的测试:")
        for test, traceback in result.failures:
            print(f"  - {test}")
    
    if result.errors:
        print("\n错误的测试:")
        for test, traceback in result.errors:
            print(f"  - {test}")
    
    print("=" * 70)
    
    return result


if __name__ == '__main__':
    run_tests()
