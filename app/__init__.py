"""
应用工厂
提供Flask应用创建和配置功能
"""
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
import os
import uuid
from flask import request, g, jsonify
import logging

_logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

# 初始化扩展
db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri=os.getenv("LIMITER_STORAGE_URI", "memory://")
)


FASTAPI_URL = os.getenv("FASTAPI_URL", "http://127.0.0.1:5002")


def _register_fastapi_proxy(app, csrf):
    """注册 FastAPI 反向代理路由，将 /api/v1/ 请求转发到 FastAPI 服务。

    仅在非 Nginx 环境（本地开发）下启用。
    生产环境由 Nginx 直接代理 /api/v1/ 到 FastAPI，无需此中间层。
    设置环境变量 NGINX_PROXY=1 可禁用此代理。
    """
    # 检测是否在 Nginx 代理环境下运行
    if os.environ.get('NGINX_PROXY', '').lower() in ('1', 'true', 'yes'):
        _logger.info("Nginx 代理模式已启用，跳过 Flask 内置 /api/v1/ 代理路由")
        return

    import urllib.request
    import urllib.error

    @app.route('/api/v1/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
    @csrf.exempt
    def proxy_to_fastapi(path):
        # SSRF防护：拒绝路径遍历
        if '..' in path.split('/'):
            return jsonify({'success': False, 'message': '非法请求路径'}), 400

        # 构建完整的目标 URL（包含查询参数）
        query_string = request.query_string.decode('utf-8') if request.query_string else ''
        target_url = f"{FASTAPI_URL}/api/v1/{path}"
        if query_string:
            target_url += f"?{query_string}"

        # SSRF防护：验证解析后的URL仍指向目标FastAPI主机
        from urllib.parse import urlparse
        parsed = urlparse(target_url)
        expected = urlparse(FASTAPI_URL)
        if parsed.scheme not in ('http', 'https') or parsed.netloc != expected.netloc:
            return jsonify({'success': False, 'message': '非法请求目标'}), 400

        try:
            req = urllib.request.Request(
                target_url,
                data=request.get_data(),
                method=request.method,
            )
            # 转发关键请求头（含 Origin/Referer/Host，供 FastAPI CSRF 中间件校验）
            for header in ['Content-Type', 'Authorization', 'Cookie', 'Origin', 'Referer', 'Host']:
                val = request.headers.get(header)
                if val:
                    req.add_header(header, val)

            resp = urllib.request.urlopen(req, timeout=60)
            content = resp.read()
            status_code = resp.getcode()
            # 透传响应头
            headers = []
            for name, value in resp.getheaders():
                if name.lower() not in ('content-encoding', 'content-length', 'transfer-encoding', 'connection'):
                    headers.append((name, value))
            return app.response_class(content, status=status_code, headers=headers)

        except urllib.error.HTTPError as e:
            content = e.read()
            return app.response_class(content, status=e.code)
        except urllib.error.URLError:
            return jsonify({'success': False, 'message': 'FastAPI 服务未启动，请检查服务状态'}), 503
        except Exception as e:
            _logger.error(f'代理请求失败: {str(e)}')
            return jsonify({'success': False, 'message': '代理请求失败'}), 500


def create_app(config_name='default'):
    """
    应用工厂函数

    Args:
        config_name: 配置名称(default/development/production/testing)

    Returns:
        Flask应用实例
    """
    # 获取项目根目录
    basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

    # 创建Flask应用，指定模板和静态文件路径
    app = Flask(__name__,
                template_folder=os.path.join(basedir, 'templates'),
                static_folder=os.path.join(basedir, 'static'))
    
    # 加载配置
    config = get_config(config_name)
    app.config.update(config)
    
    # 初始化扩展
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)

    # 初始化Redis缓存 (连接失败自动降级为内存缓存)
    from utils.redis_cache import redis_cache
    redis_cache.init_app(app)

    # 数据写入后自动失效对应缓存 (POST/PUT/DELETE/PATCH)
    @app.after_request
    def _invalidate_cache_on_write(response):
        from utils.cache_manager import invalidate_cache_on_write
        return invalidate_cache_on_write(response)
    
    # 启用gzip压缩中间件（CSS/JS等文本资源压缩后体积减少60-80%）
    from utils.compression import init_compression
    init_compression(app)
    
    # 初始化日志
    from utils import logger
    logger.init_app(app)
    
    # 注入全链路 TraceId
    @app.before_request
    def before_request():
        g.trace_id = request.headers.get('X-Trace-Id', str(uuid.uuid4()))
    
    @app.after_request
    def after_request(response):
        response.headers['X-Trace-Id'] = getattr(g, 'trace_id', 'none')
        # 为AJAX请求设置CSRF token头，便于前端fetch调用
        if request.path and not request.path.startswith('/api/'):
            response.headers.set('X-CSRFToken', g.get('csrf_token', ''))
        # 记录访问日志
        from utils.logger import log_request
        return log_request(response)

    # CSRF保护已启用，API路由通过蓝图级csrf.exempt或路由装饰器豁免

    # 添加模板上下文处理器
    from datetime import datetime as dt
    @app.context_processor
    def inject_datetime():
        return {'datetime': dt}

    # 注册蓝图
    register_blueprints(app)
    
    # 导航权限缓存（使用Redis, 跨重启不丢失; Redis不可用时降级为内存缓存）
    _nav_cache_ttl = 300  # 5分钟缓存

    # 注入导航权限数据（需在蓝图注册后）
    @app.context_processor
    def inject_nav_permissions():
        import time
        from utils.redis_cache import redis_cache

        # 优先从Redis读取
        cached = redis_cache.get('nav_sections')
        if cached is not None:
            return {'nav_sections': cached}

        from app.models import Permission

        nav_items = Permission.query.filter(
            Permission.parent_id.is_(None),
            Permission.is_nav == True
        ).order_by(Permission.section, Permission.sort_order).all()

        SPECIAL_PERMISSION_MAP = {
            'material_calculator': 'product_manage',
            'material_registration': 'product_manage',
            'supplier_manage': 'product_manage',
            'stock_view': ['stock_view', 'stockin_manage', 'stockout_manage'],
            'sku_batch_manage': 'sku_batch_view',
            'order_manage': ['order_manage', 'stockin_manage'],
            'production_plan_view': ['production_plan_view', 'production_plan_manage'],
            'production_summary_view': ['production_summary_view', 'production_summary_manage'],
        }

        sections = {}
        for item in nav_items:
            section_key = item.section or 'other'
            if section_key not in sections:
                sections[section_key] = {
                    'name': item.section_name or section_key,
                    'items': []
                }

            perm_codes = SPECIAL_PERMISSION_MAP.get(item.code, [item.code])
            if not isinstance(perm_codes, list):
                perm_codes = [perm_codes]

            item_dict = {
                'id': item.id,
                'name': item.name,
                'code': item.code,
                'icon': item.icon,
                'url': item.url,
                'permission_codes': perm_codes
            }
            sections[section_key]['items'].append(item_dict)

        section_order = ['purchase', 'purchase_tools', 'core', 'finance', 'data', 'sku_batch', 'system']
        ordered_sections = {}
        for key in section_order:
            if key in sections:
                ordered_sections[key] = sections[key]
        for key in sections:
            if key not in ordered_sections:
                ordered_sections[key] = sections[key]

        # 写入Redis缓存
        redis_cache.set('nav_sections', ordered_sections, timeout=_nav_cache_ttl)

        return {'nav_sections': ordered_sections}
    
    # 请注意：引入 Flask-Migrate 后，不再使用 db.create_all()，改为由 Alembic 脚本控制
    # with app.app_context():
    #     db.create_all()
    
    return app


def get_config(config_name):
    """获取配置"""
    configs = {
        'default': {
            'SECRET_KEY': os.environ.get('SECRET_KEY') or (None if os.environ.get('FLASK_ENV') == 'production' else 'dev-key-for-local-only'),
            'SQLALCHEMY_DATABASE_URI': get_database_uri(),
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
            'SQLALCHEMY_POOL_SIZE': int(os.environ.get('DB_POOL_SIZE', 10)),
            'SQLALCHEMY_POOL_RECYCLE': int(os.environ.get('DB_POOL_RECYCLE', 1800)),
            'SQLALCHEMY_POOL_TIMEOUT': int(os.environ.get('DB_POOL_TIMEOUT', 30)),
            'SQLALCHEMY_MAX_OVERFLOW': int(os.environ.get('DB_MAX_OVERFLOW', 5)),
            'SQLALCHEMY_POOL_PRE_PING': True,
            'SQLALCHEMY_ECHO': os.environ.get('SQL_ECHO', 'false').lower() == 'true',
            'WTF_CSRF_ENABLED': True,
            'UPLOAD_FOLDER': os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads'),
            'MAX_CONTENT_LENGTH': 16 * 1024 * 1024,
            'SESSION_COOKIE_SECURE': os.environ.get('FLASK_ENV') == 'production',
            'SESSION_COOKIE_HTTPONLY': True,
            'SESSION_COOKIE_SAMESITE': 'Lax',
            'SEND_FILE_MAX_AGE_DEFAULT': 0,
            'ASSET_VERSION': '2.5',  # CSS/JS缓存清除版本号，更新静态文件时递增此值
            'TEMPLATES_AUTO_RELOAD': True,
        },
        'testing': {
            'SECRET_KEY': os.environ.get('TEST_SECRET_KEY', 'test-secret-key-for-testing-only'),
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
            'WTF_CSRF_ENABLED': False,
            'TESTING': True,
        }
    }
    
    flask_env = os.environ.get('FLASK_ENV', 'development')
    
    if flask_env == 'production':
        if not configs['default']['SECRET_KEY']:
            raise RuntimeError("PRODUCTION ERROR: SECRET_KEY must be set in environment variables!")
        _logger.warning("Running in PRODUCTION mode. Ensure you are using HTTPS!")
        _logger.warning("SESSION_COOKIE_SECURE is enabled - session cookies require HTTPS")
    else:
        _logger.info("Running in %s mode", flask_env.upper())
    
    return configs.get(config_name, configs['default'])


def get_database_uri():
    """获取数据库URI"""
    db_type = os.getenv('DB_TYPE', 'sqlite')
    
    if db_type == 'mysql':
        db_host = os.getenv('DB_HOST', 'localhost')
        db_port = os.getenv('DB_PORT', '3306')
        db_user = os.getenv('DB_USER')
        db_password = os.getenv('DB_PASSWORD')
        db_name = os.getenv('DB_NAME', 'erp_system')
        
        # 生产环境下必须提供数据库凭证
        if os.environ.get('FLASK_ENV') == 'production':
            if not db_user or not db_password:
                raise RuntimeError("PRODUCTION ERROR: DB_USER and DB_PASSWORD must be set for MySQL!")
        
        # 非生产环境下的兜底
        db_user = db_user or 'root'
        db_password = db_password or ''
        
        return f'mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}?charset=utf8mb4'
    else:
        return 'sqlite:///erp.db'


def register_blueprints(app):
    """注册蓝图"""
    def _register(bp_import_path, bp_name, csrf_exempt=False, url_prefix=None):
        """统一蓝图注册辅助函数"""
        try:
            module = __import__(bp_import_path, fromlist=[bp_name])
            bp = getattr(module, bp_name)
            if csrf_exempt:
                csrf.exempt(bp)
            if url_prefix:
                app.register_blueprint(bp, url_prefix=url_prefix)
            else:
                app.register_blueprint(bp)
            _logger.info("蓝图注册成功: %s", bp_name)
        except ImportError as e:
            _logger.error("蓝图注册失败 %s: %s", bp_name, e)

    _register('app.routes.main', 'main_bp')
    _register('app.routes.product', 'product_bp')
    _register('app.routes.order', 'order_bp')
    _register('app.routes.stock', 'stock_bp')
    _register('app.routes.api', 'api_bp')
    _register('app.routes.user', 'user_bp')
    _register('app.routes.report', 'report_bp')
    _register('app.routes.case', 'case_page_bp')
    _register('app.routes.case', 'case_api_bp')
    _register('app.routes.approval', 'approval_bp', csrf_exempt=True)
    _register('app.routes.customer', 'customer_bp', csrf_exempt=True)
    _register('app.routes.supplier', 'supplier_bp', csrf_exempt=True)
    _register('app.routes.staging_order', 'staging_order_bp', csrf_exempt=True, url_prefix='/api/staging')
    _register('app.routes.batch', 'batch_bp', csrf_exempt=True, url_prefix='/api/batch')
    _register('app.routes.staging_stockin', 'staging_stockin_bp', csrf_exempt=True, url_prefix='/api/staging')
    _register('app.routes.staging_stockout', 'staging_stockout_bp', csrf_exempt=True, url_prefix='/api/staging')
    _register('app.routes.material', 'material_bp', csrf_exempt=True)
    _register('app.routes.purchase_center', 'purchase_center_bp', csrf_exempt=True)
    _register('app.routes.material_registration', 'material_registration_bp', csrf_exempt=True)
    _register('app.routes.customer_order', 'customer_order_bp')
    _register('app.routes.sku_batch', 'sku_batch_bp', csrf_exempt=True)
    _register('app.routes.finance', 'finance_bp')
    _register('app.routes.production_plan', 'production_plan_bp')
    _register('app.routes.purchase_plan', 'purchase_plan_bp')
    _register('app.routes.production_summary', 'production_summary_bp')

    # FastAPI 反向代理 - 将 /api/v1/ 请求转发到 FastAPI 服务（豁免CSRF）
    _register_fastapi_proxy(app, csrf)



# 为了向后兼容,创建一个默认应用实例
app = create_app()


if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', '0') == '1'
    host = os.getenv('FLASK_HOST', '127.0.0.1')
    port = int(os.getenv('FLASK_PORT', '5003'))
    app.run(debug=debug_mode, host=host, port=port)
