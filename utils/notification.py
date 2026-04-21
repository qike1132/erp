"""
通知系统
提供消息通知和提醒功能 (FastAPI 兼容版本)
"""
from datetime import datetime
from typing import Dict, List, Any, Optional
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Base


# 通知数据模型
class Notification(Base):
    """通知模型"""
    __tablename__ = 'notification'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=True)
    title = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    type = Column(String(20), default='info')  # info, warning, error, success
    category = Column(String(50))  # order, stock, system
    is_read = Column(Boolean, default=False)
    link = Column(String(200))  # 相关链接
    create_time = Column(DateTime, default=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'content': self.content,
            'type': self.type,
            'category': self.category,
            'is_read': self.is_read,
            'link': self.link,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S')
        }


class NotificationService:
    """通知服务"""
    
    @staticmethod
    def create_notification(title: str, content: str, 
                          notification_type: str = 'info',
                          category: str = None,
                          user_id: int = None,
                          link: str = None) -> Notification:
        """
        创建通知
        
        Args:
            title: 通知标题
            content: 通知内容
            notification_type: 通知类型(info/warning/error/success)
            category: 通知分类
            user_id: 用户ID(可选,为空则通知所有用户)
            link: 相关链接
        """
        session = SyncSessionLocal()
        try:
            notification = Notification(
                user_id=user_id,
                title=title,
                content=content,
                type=notification_type,
                category=category,
                link=link
            )
            session.add(notification)
            session.commit()
            return notification
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    @staticmethod
    def get_user_notifications(user_id: int, 
                              unread_only: bool = False,
                              limit: int = 20) -> List[Notification]:
        """
        获取用户通知
        
        Args:
            user_id: 用户ID
            unread_only: 是否只获取未读通知
            limit: 限制数量
        """
        session = SyncSessionLocal()
        try:
            query = session.query(Notification).filter(
                (Notification.user_id == user_id) | (Notification.user_id.is_(None))
            )
            
            if unread_only:
                query = query.filter(Notification.is_read == False)
            
            return query.order_by(Notification.create_time.desc()).limit(limit).all()
        finally:
            session.close()
    
    @staticmethod
    def mark_as_read(notification_id: int) -> bool:
        """标记通知为已读"""
        session = SyncSessionLocal()
        try:
            notification = session.query(Notification).get(notification_id)
            if notification:
                notification.is_read = True
                session.commit()
                return True
            return False
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    @staticmethod
    def mark_all_as_read(user_id: int) -> int:
        """标记所有通知为已读"""
        session = SyncSessionLocal()
        try:
            count = session.query(Notification).filter(
                (Notification.user_id == user_id) | (Notification.user_id.is_(None)),
                Notification.is_read == False
            ).update({'is_read': True})
            session.commit()
            return count
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    @staticmethod
    def get_unread_count(user_id: int) -> int:
        """获取未读通知数量"""
        session = SyncSessionLocal()
        try:
            return session.query(Notification).filter(
                (Notification.user_id == user_id) | (Notification.user_id.is_(None)),
                Notification.is_read == False
            ).count()
        finally:
            session.close()


# 预定义的通知类型
class NotificationType:
    """通知类型常量"""
    INFO = 'info'
    WARNING = 'warning'
    ERROR = 'error'
    SUCCESS = 'success'


class NotificationCategory:
    """通知分类常量"""
    ORDER = 'order'  # 订单相关
    STOCK = 'stock'  # 库存相关
    SYSTEM = 'system'  # 系统通知


# 通知模板
class NotificationTemplates:
    """通知模板"""
    
    @staticmethod
    def order_created(order_no: str, customer: str) -> Dict:
        """订单创建通知"""
        return {
            'title': '新订单创建',
            'content': f'订单 {order_no} 已创建,客户:{customer}',
            'type': NotificationType.INFO,
            'category': NotificationCategory.ORDER
        }
    
    @staticmethod
    def order_status_changed(order_no: str, old_status: str, new_status: str) -> Dict:
        """订单状态变更通知"""
        return {
            'title': '订单状态变更',
            'content': f'订单 {order_no} 状态从 {old_status} 变更为 {new_status}',
            'type': NotificationType.INFO,
            'category': NotificationCategory.ORDER
        }
    
    @staticmethod
    def stock_low(product_name: str, current_stock: int, min_stock: int) -> Dict:
        """库存不足预警"""
        return {
            'title': '库存不足预警',
            'content': f'产品 {product_name} 库存不足,当前库存:{current_stock},最低库存:{min_stock}',
            'type': NotificationType.WARNING,
            'category': NotificationCategory.STOCK
        }
    
    @staticmethod
    def stockin_completed(stockin_no: str, quantity: int) -> Dict:
        """备货完成通知"""
        return {
            'title': '备货完成',
            'content': f'备货单 {stockin_no} 已完成,数量:{quantity}',
            'type': NotificationType.SUCCESS,
            'category': NotificationCategory.STOCK
        }
    
    @staticmethod
    def stockout_completed(stockout_no: str, quantity: int) -> Dict:
        """出货完成通知"""
        return {
            'title': '出货完成',
            'content': f'出货单 {stockout_no} 已完成,数量:{quantity}',
            'type': NotificationType.SUCCESS,
            'category': NotificationCategory.STOCK
        }


if __name__ == '__main__':
    print("通知系统模块")
    print("\n使用示例:")
    print("""
# 1. 创建通知
from utils.notification import NotificationService, NotificationTemplates

# 使用模板创建通知
template = NotificationTemplates.order_created('ORD001', '测试客户')
NotificationService.create_notification(**template)

# 2. 获取用户通知
notifications = NotificationService.get_user_notifications(user_id=1)

# 3. 标记已读
NotificationService.mark_as_read(notification_id=1)

# 4. 获取未读数量
count = NotificationService.get_unread_count(user_id=1)
    """)
