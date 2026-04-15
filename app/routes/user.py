"""
用户管理路由蓝图
包含用户CRUD和权限设置功能
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from app import db
from app.models import User, Permission
from werkzeug.security import generate_password_hash
from utils.password_validator import PasswordValidator
from utils.sanitizer import sanitize_plain_text

user_bp = Blueprint('user', __name__, url_prefix='/user')


def user_permission_required(permission_code):
    """用户权限验证装饰器"""
    def decorator(f):
        def decorated_function(*args, **kwargs):
            if not session.get('user_id'):
                return redirect(url_for('main.login'))
            user = db.session.get(User, session['user_id'])
            if not user:
                session.clear()
                return redirect(url_for('main.login'))
            if user.is_super:
                return f(*args, **kwargs)
            has_permission = False
            for p in user.permissions:
                if p.code == permission_code:
                    has_permission = True
                    break
            if not has_permission:
                flash('无权限访问该页面', 'error')
                return redirect(url_for('main.index'))
            return f(*args, **kwargs)
        decorated_function.__name__ = f.__name__
        return decorated_function
    return decorator


@user_bp.route('/users')
@user_permission_required('user_manage')
def users():
    """用户列表页面"""
    current_user = db.session.get(User, session['user_id'])
    if not current_user.is_super:
        flash('无权限访问', 'error')
        return redirect(url_for('main.index'))
    users = User.query.all()
    return render_template('user.html', users=users)


@user_bp.route('/add', methods=['POST'])
@user_permission_required('user_manage')
def add_user():
    """添加用户"""
    current_user = db.session.get(User, session['user_id'])
    if not current_user.is_super:
        flash('无权限访问', 'error')
        return redirect(url_for('main.index'))

    username = sanitize_plain_text(request.form.get('username', '').strip())
    password = request.form.get('password')
    is_super = request.form.get('is_super') == 'on'

    if not username or not password:
        flash('用户名和密码不能为空', 'error')
        return redirect(url_for('user.users'))

    is_valid, error_msg = PasswordValidator.validate(password)
    if not is_valid:
        flash(error_msg, 'error')
        return redirect(url_for('user.users'))

    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
        flash('用户名已存在', 'error')
        return redirect(url_for('user.users'))

    new_user = User(
        username=username,
        password=generate_password_hash(password),
        is_super=is_super
    )
    db.session.add(new_user)
    db.session.commit()
    flash('用户添加成功', 'success')
    return redirect(url_for('user.users'))


@user_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@user_permission_required('user_manage')
def edit_user(id):
    """编辑用户"""
    current_user = db.session.get(User, session['user_id'])
    if not current_user.is_super:
        flash('无权限访问', 'error')
        return redirect(url_for('main.index'))

    user = User.query.get_or_404(id)
    if request.method == 'POST':
        password = request.form.get('password')
        if password:
            is_valid, error_msg = PasswordValidator.validate(password)
            if not is_valid:
                flash(error_msg, 'error')
                return redirect(url_for('user.users'))
            user.password = generate_password_hash(password)
        user.is_super = request.form.get('is_super') == 'on'
        db.session.commit()
        flash('用户编辑成功', 'success')
        return redirect(url_for('user.users'))
    return render_template('edit_user.html', user=user)


@user_bp.route('/toggle/<int:id>')
@user_permission_required('user_manage')
def toggle_user_status(id):
    """切换用户状态"""
    current_user = db.session.get(User, session['user_id'])
    if not current_user.is_super:
        flash('无权限访问', 'error')
        return redirect(url_for('main.index'))

    user = User.query.get_or_404(id)
    if user.is_super:
        flash('超级用户不能禁用', 'error')
        return redirect(url_for('user.users'))

    user.status = not user.status
    db.session.commit()
    flash('用户状态已更新', 'success')
    return redirect(url_for('user.users'))


@user_bp.route('/delete/<int:id>')
@user_permission_required('user_manage')
def delete_user(id):
    """删除用户"""
    current_user = db.session.get(User, session['user_id'])
    if not current_user.is_super:
        flash('无权限访问', 'error')
        return redirect(url_for('main.index'))

    user = User.query.get_or_404(id)
    if user.is_super:
        flash('超级用户不能删除', 'error')
        return redirect(url_for('user.users'))

    db.session.delete(user)
    db.session.commit()
    flash('用户已删除', 'success')
    return redirect(url_for('user.users'))


@user_bp.route('/permission/<int:user_id>', methods=['GET', 'POST'])
@user_permission_required('user_manage')
def user_permission(user_id):
    """用户权限设置"""
    current_user = db.session.get(User, session['user_id'])
    if not current_user.is_super:
        flash('无权限访问', 'error')
        return redirect(url_for('main.index'))

    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        user.permissions.clear()
        permission_ids = request.form.getlist('permission_ids')

        SENSITIVE_PERMISSIONS = ['user_manage']

        for pid in permission_ids:
            permission = db.session.get(Permission, int(pid))
            if permission:
                if permission.code in SENSITIVE_PERMISSIONS:
                    continue
                user.permissions.append(permission)
                for child in permission.children:
                    if child not in user.permissions:
                        user.permissions.append(child)

        db.session.commit()
        flash('权限设置成功', 'success')
        return redirect(url_for('user.users'))

    permissions = Permission.query.all()

    parent_permissions = [p for p in permissions if p.parent_id is None]

    SENSITIVE_PERMISSIONS = ['user_manage']
    visible_permissions = [p for p in parent_permissions if p.code not in SENSITIVE_PERMISSIONS]

    user_permission_ids = [p.id for p in user.permissions]
    return render_template('permission.html', user=user, permissions=visible_permissions, user_permission_ids=user_permission_ids)