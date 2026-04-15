"""
统一权限装饰器模块
提供API权限、页面权限和管理员权限检查装饰器
"""
from functools import wraps
from flask import session, jsonify, redirect, url_for, flash, request
from app.models import User
import logging

logger = logging.getLogger(__name__)


def api_permission_required(permission_name):
    """
    API权限检查装饰器 - 返回JSON响应
    
    Args:
        permission_name: 权限代码，如 'product_manage', 'order_manage' 等
    
    Returns:
        装饰器函数，如果权限验证失败返回JSON错误响应
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 获取客户端IP和请求路径
            client_ip = request.remote_addr or "unknown"
            request_path = request.path or "unknown"
            
            if 'user_id' not in session:
                logger.warning(
                    f"[Auth] API权限检查失败: 未登录, IP={client_ip}, "
                    f"path={request_path}, permission={permission_name}"
                )
                return jsonify({'error': '未登录', 'success': False}), 401
            
            user = User.query.get(session['user_id'])
            if not user:
                logger.warning(
                    f"[Auth] API权限检查失败: 用户不存在, IP={client_ip}, "
                    f"user_id={session.get('user_id')}, path={request_path}"
                )
                session.clear()
                return jsonify({'error': '用户不存在', 'success': False}), 401
            
            if not user.has_permission(permission_name):
                logger.warning(
                    f"[Auth] API权限检查失败: 权限不足, IP={client_ip}, "
                    f"user={user.username}, required_permission={permission_name}, "
                    f"path={request_path}"
                )
                return jsonify({'error': '权限不足', 'success': False}), 403
            
            logger.debug(
                f"[Auth] API权限检查通过: IP={client_ip}, user={user.username}, "
                f"permission={permission_name}, path={request_path}"
            )
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def page_permission_required(permission_name):
    """
    页面权限检查装饰器 - 返回HTML页面重定向
    
    Args:
        permission_name: 权限代码，如 'product_manage', 'order_manage' 等
    
    Returns:
        装饰器函数，如果权限验证失败返回重定向响应
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 获取客户端IP和请求路径
            client_ip = request.remote_addr or "unknown"
            request_path = request.path or "unknown"
            
            if 'user_id' not in session:
                logger.warning(
                    f"[Auth] 页面权限检查失败: 未登录, IP={client_ip}, "
                    f"path={request_path}, permission={permission_name}"
                )
                flash('请先登录', 'error')
                return redirect(url_for('main.login'))
            
            user = User.query.get(session['user_id'])
            if not user:
                logger.warning(
                    f"[Auth] 页面权限检查失败: 用户不存在, IP={client_ip}, "
                    f"user_id={session.get('user_id')}, path={request_path}"
                )
                session.clear()
                flash('用户不存在，请重新登录', 'error')
                return redirect(url_for('main.login'))
            
            if not user.has_permission(permission_name):
                logger.warning(
                    f"[Auth] 页面权限检查失败: 权限不足, IP={client_ip}, "
                    f"user={user.username}, required_permission={permission_name}, "
                    f"path={request_path}"
                )
                flash('权限不足，无法访问该页面', 'error')
                return redirect(url_for('main.index'))
            
            logger.debug(
                f"[Auth] 页面权限检查通过: IP={client_ip}, user={user.username}, "
                f"permission={permission_name}, path={request_path}"
            )
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_required(f):
    """
    管理员权限检查装饰器
    检查用户是否为超级管理员(is_super=True)
    支持API请求和页面请求两种模式
    
    Returns:
        装饰器函数，如果权限验证失败返回相应的错误响应
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 获取客户端IP和请求路径
        client_ip = request.remote_addr or "unknown"
        request_path = request.path or "unknown"
        is_api = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        if 'user_id' not in session:
            if is_api:
                logger.warning(
                    f"[Auth] 管理员权限检查失败: 未登录 (API请求), "
                    f"IP={client_ip}, path={request_path}"
                )
                return jsonify({'error': '请先登录', 'success': False}), 401
            logger.warning(
                f"[Auth] 管理员权限检查失败: 未登录 (页面请求), "
                f"IP={client_ip}, path={request_path}"
            )
            flash('请先登录！', 'error')
            return redirect(url_for('main.login'))
        
        user = User.query.get(session['user_id'])
        if not user:
            if is_api:
                logger.warning(
                    f"[Auth] 管理员权限检查失败: 用户不存在, "
                    f"IP={client_ip}, user_id={session.get('user_id')}, path={request_path}"
                )
                return jsonify({'error': '用户不存在', 'success': False}), 401
            logger.warning(
                f"[Auth] 管理员权限检查失败: 用户不存在, "
                f"IP={client_ip}, user_id={session.get('user_id')}, path={request_path}"
            )
            flash('用户不存在！', 'error')
            return redirect(url_for('main.login'))
        
        if not user.is_super:
            if is_api:
                logger.warning(
                    f"[Auth] 管理员权限检查失败: 非管理员, "
                    f"IP={client_ip}, user={user.username}, path={request_path}"
                )
                return jsonify({'error': '需要管理员权限', 'success': False}), 403
            logger.warning(
                f"[Auth] 管理员权限检查失败: 非管理员, "
                f"IP={client_ip}, user={user.username}, path={request_path}"
            )
            flash('需要管理员权限！', 'error')
            return redirect(url_for('main.index'))
        
        logger.debug(
            f"[Auth] 管理员权限检查通过: IP={client_ip}, user={user.username}, "
            f"path={request_path}"
        )
        return f(*args, **kwargs)
    return decorated_function


def get_current_user():
    """
    获取当前登录用户
    
    Returns:
        User对象或None
    """
    if 'user_id' not in session:
        return None
    return User.query.get(session['user_id'])


def is_admin(user):
    """
    检查用户是否为管理员（超级用户）
    
    Args:
        user: User对象
    
    Returns:
        bool: 如果是管理员返回True，否则返回False
    """
    return user and user.is_super
