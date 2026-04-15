"""
Swagger API文档配置
"""
from flasgger import Swagger


def setup_swagger(app):
    """
    配置Swagger API文档
    
    Args:
        app: Flask应用实例
    
    Returns:
        Swagger: Swagger实例
    """
    swagger_config = {
        "headers": [],
        "specs": [
            {
                "endpoint": 'apispec',
                "route": '/apispec.json',
                "rule_filter": lambda rule: True,
                "model_filter": lambda tag: True,
            }
        ],
        "static_url_path": '/flasgger_static',
        "swagger_ui": True,
        "specs_route": '/api/docs'
    }
    
    swagger_template = {
        "swagger": "2.0",
        "info": {
            "title": "ERP系统API文档",
            "description": "滨发玩具协同系统API接口文档",
            "version": "1.0.0",
            "contact": {
                "name": "ERP系统",
                "email": "support@example.com"
            }
        },
        "host": "localhost:5003",
        "basePath": "/",
        "schemes": ["http"],
        "securityDefinitions": {
            "Bearer": {
                "type": "apiKey",
                "name": "Authorization",
                "in": "header",
                "description": "JWT Token"
            }
        }
    }
    
    swagger = Swagger(
        app,
        config=swagger_config,
        template=swagger_template
    )
    
    return swagger


# API文档模板
PRODUCT_API_DOCS = {
    'tags': ['产品管理'],
    'parameters': [
        {
            'name': 'id',
            'in': 'path',
            'type': 'integer',
            'required': True,
            'description': '产品ID'
        }
    ],
    'responses': {
        200: {
            'description': '成功',
            'schema': {
                'type': 'object',
                'properties': {
                    'id': {'type': 'integer'},
                    'name': {'type': 'string'},
                    'barcode': {'type': 'string'},
                    'current_stock': {'type': 'integer'}
                }
            }
        },
        404: {
            'description': '产品不存在'
        }
    }
}

ORDER_API_DOCS = {
    'tags': ['订单管理'],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'customer': {'type': 'string'},
                    'product_id': {'type': 'integer'},
                    'quantity': {'type': 'integer'}
                },
                'required': ['customer', 'product_id', 'quantity']
            }
        }
    ],
    'responses': {
        201: {
            'description': '订单创建成功'
        },
        400: {
            'description': '参数错误'
        }
    }
}
