"""
审批管理公共工具函数
"""
from flask import session
from app import db
from app.models import User, ApprovalLog
import json


def get_current_user():
    """获取当前登录用户"""
    if 'user_id' not in session:
        return None
    return User.query.get(session['user_id'])


def create_approval_log(approval_request, action, actor, details=None):
    """创建审批日志
    
    Args:
        approval_request: 审批请求对象
        action: 操作动作 (create/approve/reject/cancel/execute)
        actor: 操作人对象
        details: 操作详情字典
    
    Returns:
        ApprovalLog: 创建的日志对象
    """
    log = ApprovalLog(
        approval_request_id=approval_request.id,
        action=action,
        actor_id=actor.id if actor else None,
        actor_name=actor.username if actor else None,
        details=json.dumps(details, ensure_ascii=False) if details else None
    )
    db.session.add(log)
    return log


def validate_order_data(customer, quantity, note=''):
    """验证订单数据
    
    Args:
        customer: 客户名称
        quantity: 数量
        note: 备注
    
    Returns:
        tuple: (is_valid, error_message)
    """
    # 验证数量
    try:
        quantity = int(quantity)
    except (ValueError, TypeError):
        return False, '数量必须是有效的整数'
    
    if quantity <= 0:
        return False, '数量必须大于0'
    
    if quantity > 100000:
        return False, '数量超出合理范围（最大100000）'
    
    # 验证客户名称
    customer = str(customer).strip()
    if not customer:
        return False, '客户名称不能为空'
    
    if len(customer) > 100:
        return False, '客户名称过长（最大100字符）'
    
    # 验证备注
    note = str(note).strip()
    if len(note) > 500:
        return False, '备注过长（最大500字符）'
    
    return True, None
