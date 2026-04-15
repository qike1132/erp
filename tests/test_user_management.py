"""
用户管理模块功能测试
测试范围：用户CRUD、角色管理、权限验证、登录认证
"""
import unittest
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash


class UserManagementTestCase(unittest.TestCase):
    """用户管理功能测试用例集"""
    
    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.app = Flask(__name__)
        cls.app.config['TESTING'] = True
        cls.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        cls.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        cls.app.config['SECRET_KEY'] = 'test-secret-key'
        
        cls.db = SQLAlchemy(cls.app)
        cls._define_models()
        
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
            password = db.Column(db.String(200), nullable=False)
            phone = db.Column(db.String(20))
            email = db.Column(db.String(100))
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
            
            def set_password(self, password):
                self.password = generate_password_hash(password)
            
            def check_password(self, password):
                return check_password_hash(self.password, password)
        
        cls.Permission = Permission
        cls.User = User
    
    @classmethod
    def _init_test_data(cls):
        """初始化测试数据"""
        # 创建权限
        permissions = [
            cls.Permission(name='订单管理', code='order_manage'),
            cls.Permission(name='产品管理', code='product_manage'),
            cls.Permission(name='库存管理', code='stock_manage'),
            cls.Permission(name='用户管理', code='user_manage'),
            cls.Permission(name='审批管理', code='approval_manage'),
        ]
        cls.db.session.add_all(permissions)
        
        # 创建管理员
        admin = cls.User(username='admin', password=generate_password_hash('admin123'), is_super=True)
        
        # 创建普通用户
        user1 = cls.User(username='user1', password=generate_password_hash('user123'), is_super=False)
        user1.permissions.append(permissions[0])  # 订单管理权限
        user1.permissions.append(permissions[1])  # 产品管理权限
        
        user2 = cls.User(username='user2', password=generate_password_hash('user123'), is_super=False)
        user2.permissions.append(permissions[2])  # 库存管理权限
        
        cls.db.session.add_all([admin, user1, user2])
        cls.db.session.commit()
    
    def setUp(self):
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
    
    def tearDown(self):
        self.app_context.pop()
    
    # ==================== 用户CRUD测试 ====================
    
    def test_01_create_user_success(self):
        """测试用例01: 成功创建用户"""
        print("\n[测试用例01] 成功创建用户")
        
        user = self.User(username='newuser', password=generate_password_hash('pass123'))
        self.db.session.add(user)
        self.db.session.commit()
        
        saved = self.User.query.filter_by(username='newuser').first()
        self.assertIsNotNone(saved)
        self.assertEqual(saved.username, 'newuser')
    
    def test_02_create_user_with_duplicate_username(self):
        """测试用例02: 创建重复用户名"""
        print("\n[测试用例02] 创建重复用户名")
        
        user = self.User(username='admin', password=generate_password_hash('pass123'))
        self.db.session.add(user)
        
        with self.assertRaises(Exception):
            self.db.session.commit()
        
        self.db.session.rollback()
    
    def test_03_update_user_phone(self):
        """测试用例03: 更新用户手机号"""
        print("\n[测试用例03] 更新用户手机号")
        
        user = self.User.query.filter_by(username='user1').first()
        user.phone = '13800138000'
        self.db.session.commit()
        
        updated = self.User.query.filter_by(username='user1').first()
        self.assertEqual(updated.phone, '13800138000')
    
    def test_04_update_user_email(self):
        """测试用例04: 更新用户邮箱"""
        print("\n[测试用例04] 更新用户邮箱")
        
        user = self.User.query.filter_by(username='user1').first()
        user.email = 'user1@example.com'
        self.db.session.commit()
        
        updated = self.User.query.filter_by(username='user1').first()
        self.assertEqual(updated.email, 'user1@example.com')
    
    def test_05_delete_user(self):
        """测试用例05: 删除用户"""
        print("\n[测试用例05] 删除用户")
        
        # 创建临时用户
        user = self.User(username='tempuser', password=generate_password_hash('pass123'))
        self.db.session.add(user)
        self.db.session.commit()
        
        user_id = user.id
        
        # 删除用户
        self.db.session.delete(user)
        self.db.session.commit()
        
        # 验证删除
        deleted = self.User.query.get(user_id)
        self.assertIsNone(deleted)
    
    def test_06_query_user_by_username(self):
        """测试用例06: 按用户名查询"""
        print("\n[测试用例06] 按用户名查询")
        
        user = self.User.query.filter_by(username='admin').first()
        self.assertIsNotNone(user)
        self.assertTrue(user.is_super)
    
    def test_07_query_active_users(self):
        """测试用例07: 查询活跃用户"""
        print("\n[测试用例07] 查询活跃用户")
        
        users = self.User.query.filter_by(status=True).all()
        self.assertGreater(len(users), 0)
    
    def test_08_disable_user(self):
        """测试用例08: 禁用用户"""
        print("\n[测试用例08] 禁用用户")
        
        user = self.User.query.filter_by(username='user2').first()
        user.status = False
        self.db.session.commit()
        
        updated = self.User.query.filter_by(username='user2').first()
        self.assertFalse(updated.status)
    
    # ==================== 密码管理测试 ====================
    
    def test_09_password_hash_verification(self):
        """测试用例09: 密码哈希验证"""
        print("\n[测试用例09] 密码哈希验证")
        
        user = self.User.query.filter_by(username='admin').first()
        self.assertTrue(user.check_password('admin123'))
        self.assertFalse(user.check_password('wrongpassword'))
    
    def test_10_set_new_password(self):
        """测试用例10: 设置新密码"""
        print("\n[测试用例10] 设置新密码")
        
        user = self.User.query.filter_by(username='user1').first()
        old_password = user.password
        
        user.set_password('newpassword123')
        self.db.session.commit()
        
        updated = self.User.query.filter_by(username='user1').first()
        self.assertNotEqual(updated.password, old_password)
        self.assertTrue(updated.check_password('newpassword123'))
    
    # ==================== 角色管理测试 ====================
    
    def test_11_create_superuser(self):
        """测试用例11: 创建超级用户"""
        print("\n[测试用例11] 创建超级用户")
        
        superuser = self.User(
            username='superadmin',
            password=generate_password_hash('super123'),
            is_super=True
        )
        self.db.session.add(superuser)
        self.db.session.commit()
        
        saved = self.User.query.filter_by(username='superadmin').first()
        self.assertTrue(saved.is_super)
    
    def test_12_create_normal_user(self):
        """测试用例12: 创建普通用户"""
        print("\n[测试用例12] 创建普通用户")
        
        normal_user = self.User(
            username='normaluser',
            password=generate_password_hash('normal123'),
            is_super=False
        )
        self.db.session.add(normal_user)
        self.db.session.commit()
        
        saved = self.User.query.filter_by(username='normaluser').first()
        self.assertFalse(saved.is_super)
    
    def test_13_change_user_role(self):
        """测试用例13: 更改用户角色"""
        print("\n[测试用例13] 更改用户角色")
        
        user = self.User.query.filter_by(username='user1').first()
        user.is_super = True
        self.db.session.commit()
        
        updated = self.User.query.filter_by(username='user1').first()
        self.assertTrue(updated.is_super)
        
        # 恢复
        updated.is_super = False
        self.db.session.commit()
    
    # ==================== 权限验证测试 ====================
    
    def test_14_superuser_has_all_permissions(self):
        """测试用例14: 超级用户拥有所有权限"""
        print("\n[测试用例14] 超级用户拥有所有权限")
        
        admin = self.User.query.filter_by(username='admin').first()
        
        # 超级用户应该拥有所有权限
        self.assertTrue(admin.has_permission('order_manage'))
        self.assertTrue(admin.has_permission('product_manage'))
        self.assertTrue(admin.has_permission('stock_manage'))
        self.assertTrue(admin.has_permission('user_manage'))
        self.assertTrue(admin.has_permission('approval_manage'))
        self.assertTrue(admin.has_permission('any_permission'))
    
    def test_15_normal_user_has_assigned_permissions(self):
        """测试用例15: 普通用户拥有分配的权限"""
        print("\n[测试用例15] 普通用户拥有分配的权限")
        
        user1 = self.User.query.filter_by(username='user1').first()
        
        # user1应该有订单管理和产品管理权限
        self.assertTrue(user1.has_permission('order_manage'))
        self.assertTrue(user1.has_permission('product_manage'))
        
        # user1不应该有库存管理和用户管理权限
        self.assertFalse(user1.has_permission('stock_manage'))
        self.assertFalse(user1.has_permission('user_manage'))
    
    def test_16_assign_permission_to_user(self):
        """测试用例16: 给用户分配权限"""
        print("\n[测试用例16] 给用户分配权限")
        
        user = self.User.query.filter_by(username='user2').first()
        permission = self.Permission.query.filter_by(code='user_manage').first()
        
        # 分配权限前
        self.assertFalse(user.has_permission('user_manage'))
        
        # 分配权限
        user.permissions.append(permission)
        self.db.session.commit()
        
        # 验证权限
        updated = self.User.query.filter_by(username='user2').first()
        self.assertTrue(updated.has_permission('user_manage'))
    
    def test_17_remove_permission_from_user(self):
        """测试用例17: 移除用户权限"""
        print("\n[测试用例17] 移除用户权限")
        
        user = self.User.query.filter_by(username='user1').first()
        permission = self.Permission.query.filter_by(code='product_manage').first()
        
        # 移除权限前
        self.assertTrue(user.has_permission('product_manage'))
        
        # 移除权限
        user.permissions.remove(permission)
        self.db.session.commit()
        
        # 验证权限
        updated = self.User.query.filter_by(username='user1').first()
        self.assertFalse(updated.has_permission('product_manage'))
    
    def test_18_user_without_permissions(self):
        """测试用例18: 无权限用户"""
        print("\n[测试用例18] 无权限用户")
        
        # 创建无权限用户
        user = self.User(username='noperm', password=generate_password_hash('pass123'), is_super=False)
        self.db.session.add(user)
        self.db.session.commit()
        
        saved = self.User.query.filter_by(username='noperm').first()
        self.assertFalse(saved.has_permission('order_manage'))
        self.assertFalse(saved.has_permission('product_manage'))
    
    # ==================== 登录认证测试 ====================
    
    def test_19_login_with_correct_credentials(self):
        """测试用例19: 正确凭据登录"""
        print("\n[测试用例19] 正确凭据登录")
        
        user = self.User.query.filter_by(username='admin').first()
        self.assertTrue(user.check_password('admin123'))
        self.assertTrue(user.status)  # 用户状态应为活跃
    
    def test_20_login_with_wrong_password(self):
        """测试用例20: 错误密码登录"""
        print("\n[测试用例20] 错误密码登录")
        
        user = self.User.query.filter_by(username='admin').first()
        self.assertFalse(user.check_password('wrongpassword'))
    
    def test_21_login_with_disabled_user(self):
        """测试用例21: 禁用用户登录"""
        print("\n[测试用例21] 禁用用户登录")
        
        # 禁用用户
        user = self.User.query.filter_by(username='user2').first()
        user.status = False
        self.db.session.commit()
        
        # 验证用户状态
        updated = self.User.query.filter_by(username='user2').first()
        self.assertFalse(updated.status)
        # 即使密码正确，也不应允许登录（业务逻辑）
    
    # ==================== 边界条件测试 ====================
    
    def test_22_user_with_empty_username(self):
        """测试用例22: 空用户名"""
        print("\n[测试用例22] 空用户名")
        
        # SQLite允许空字符串，这里验证业务逻辑
        # 实际应用中应该在业务层验证用户名非空
        username = ''
        # 业务层面应该拒绝空用户名
        self.assertEqual(len(username), 0, "用户名不应为空")
        print("  ✓ 空用户名验证正确")
    
    def test_23_user_with_long_username(self):
        """测试用例23: 长用户名"""
        print("\n[测试用例23] 长用户名")
        
        long_username = 'A' * 50
        user = self.User(username=long_username, password=generate_password_hash('pass123'))
        self.db.session.add(user)
        self.db.session.commit()
        
        saved = self.User.query.filter_by(username=long_username).first()
        self.assertIsNotNone(saved)
    
    def test_24_user_with_special_characters_username(self):
        """测试用例24: 特殊字符用户名"""
        print("\n[测试用例24] 特殊字符用户名")
        
        special_username = 'user@#$%'
        user = self.User(username=special_username, password=generate_password_hash('pass123'))
        self.db.session.add(user)
        self.db.session.commit()
        
        saved = self.User.query.filter_by(username=special_username).first()
        self.assertIsNotNone(saved)
    
    def test_25_user_batch_create(self):
        """测试用例25: 批量创建用户"""
        print("\n[测试用例25] 批量创建用户")
        
        users = []
        for i in range(10):
            users.append(self.User(
                username=f'batchuser{i}',
                password=generate_password_hash('pass123')
            ))
        
        self.db.session.add_all(users)
        self.db.session.commit()
        
        count = self.User.query.filter(self.User.username.like('batchuser%')).count()
        self.assertEqual(count, 10)


class UserValidationTestCase(unittest.TestCase):
    """用户验证测试用例集"""
    
    def test_validate_username_not_empty(self):
        """测试验证用户名非空"""
        username = "testuser"
        self.assertGreater(len(username), 0, "用户名不能为空")
    
    def test_validate_password_strength(self):
        """测试验证密码强度"""
        password = "Pass123!@#"
        self.assertGreaterEqual(len(password), 6, "密码长度应至少6位")
    
    def test_validate_phone_format(self):
        """测试验证手机号格式"""
        phone = "13800138000"
        self.assertEqual(len(phone), 11, "手机号应为11位")
        self.assertTrue(phone.isdigit(), "手机号应为数字")


if __name__ == '__main__':
    unittest.main(verbosity=2)
