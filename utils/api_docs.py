"""
API文档配置
提供完整的API接口文档
"""
from flasgger import Swagger


def configure_swagger(app):
    """配置Swagger API文档"""
    
    app.config['SWAGGER'] = {
        'title': 'ERP系统API文档',
        'version': '1.0.0',
        'description': '''
## ERP系统API接口文档

### 认证说明
所有API接口需要在请求头中携带认证信息:
```
Authorization: Bearer <token>
```

### 错误码说明
- 200: 成功
- 201: 创建成功
- 400: 请求参数错误
- 401: 未授权
- 403: 无权限
- 404: 资源不存在
- 500: 服务器内部错误

### 主要功能模块
1. **产品管理**: 产品的增删改查
2. **订单管理**: 订单的创建和处理
3. **备货管理**: 备货单的管理
4. **出货管理**: 出货单的管理
5. **库存管理**: 库存查询和统计
6. **报表统计**: 各类业务报表
        ''',
        'uiversion': 3,
        'specs': [
            {
                'endpoint': 'apispec',
                'route': '/apispec.json',
                'rule_filter': lambda rule: True,
                'model_filter': lambda tag: True,
            }
        ],
        'static_url_path': '/flasgger_static',
        'swagger_ui': True,
        'specs_route': '/api/docs'
    }
    
    swagger = Swagger(app)
    return swagger


# API文档模板
API_DOCS = {
    'product': {
        'get_list': {
            'summary': '获取产品列表',
            'description': '获取所有产品的列表,支持分页和搜索',
            'parameters': [
                {
                    'name': 'page',
                    'in': 'query',
                    'type': 'integer',
                    'default': 1,
                    'description': '页码'
                },
                {
                    'name': 'per_page',
                    'in': 'query',
                    'type': 'integer',
                    'default': 20,
                    'description': '每页数量'
                },
                {
                    'name': 'search',
                    'in': 'query',
                    'type': 'string',
                    'description': '搜索关键词'
                }
            ],
            'responses': {
                200: {
                    'description': '产品列表',
                    'schema': {
                        'type': 'object',
                        'properties': {
                            'success': {'type': 'boolean'},
                            'data': {
                                'type': 'array',
                                'items': {
                                    'type': 'object',
                                    'properties': {
                                        'id': {'type': 'integer'},
                                        'name': {'type': 'string'},
                                        'barcode': {'type': 'string'},
                                        'current_stock': {'type': 'integer'}
                                    }
                                }
                            },
                            'total': {'type': 'integer'}
                        }
                    }
                }
            }
        },
        'create': {
            'summary': '创建产品',
            'description': '创建新的产品',
            'parameters': [
                {
                    'name': 'body',
                    'in': 'body',
                    'required': True,
                    'schema': {
                        'type': 'object',
                        'required': ['name'],
                        'properties': {
                            'name': {
                                'type': 'string',
                                'description': '产品名称',
                                'example': '测试产品'
                            },
                            'barcode': {
                                'type': 'string',
                                'description': '产品条码',
                                'example': '6901234567890'
                            },
                            'initial_stock': {
                                'type': 'integer',
                                'description': '初始库存',
                                'example': 100
                            }
                        }
                    }
                }
            ],
            'responses': {
                201: {
                    'description': '创建成功',
                    'schema': {
                        'type': 'object',
                        'properties': {
                            'success': {'type': 'boolean'},
                            'message': {'type': 'string'},
                            'data': {'type': 'object'}
                        }
                    }
                },
                400: {
                    'description': '参数错误',
                    'schema': {
                        'type': 'object',
                        'properties': {
                            'success': {'type': 'boolean'},
                            'message': {'type': 'string'},
                            'errors': {'type': 'object'}
                        }
                    }
                }
            }
        }
    },
    'order': {
        'get_list': {
            'summary': '获取订单列表',
            'description': '获取所有订单的列表',
            'parameters': [
                {
                    'name': 'status',
                    'in': 'query',
                    'type': 'string',
                    'enum': ['待备货', '部分备货', '已备货', '待出货', '已出货', '已取消'],
                    'description': '订单状态筛选'
                },
                {
                    'name': 'customer',
                    'in': 'query',
                    'type': 'string',
                    'description': '客户名称筛选'
                }
            ],
            'responses': {
                200: {
                    'description': '订单列表'
                }
            }
        },
        'create': {
            'summary': '创建订单',
            'description': '创建新的订单',
            'parameters': [
                {
                    'name': 'body',
                    'in': 'body',
                    'required': True,
                    'schema': {
                        'type': 'object',
                        'required': ['customer', 'product_id', 'quantity'],
                        'properties': {
                            'customer': {
                                'type': 'string',
                                'description': '客户名称',
                                'example': '测试客户'
                            },
                            'product_id': {
                                'type': 'integer',
                                'description': '产品ID',
                                'example': 1
                            },
                            'quantity': {
                                'type': 'integer',
                                'description': '订单数量',
                                'example': 10
                            },
                            'note': {
                                'type': 'string',
                                'description': '备注',
                                'example': '加急订单'
                            }
                        }
                    }
                }
            ],
            'responses': {
                201: {'description': '创建成功'},
                400: {'description': '参数错误'}
            }
        }
    },
    'stockin': {
        'get_list': {
            'summary': '获取备货列表',
            'description': '获取所有备货单的列表',
            'responses': {
                200: {'description': '备货列表'}
            }
        },
        'create': {
            'summary': '创建备货',
            'description': '创建新的备货单',
            'parameters': [
                {
                    'name': 'body',
                    'in': 'body',
                    'required': True,
                    'schema': {
                        'type': 'object',
                        'required': ['customer', 'product_id', 'quantity'],
                        'properties': {
                            'customer': {'type': 'string', 'description': '客户名称'},
                            'product_id': {'type': 'integer', 'description': '产品ID'},
                            'quantity': {'type': 'integer', 'description': '备货数量'}
                        }
                    }
                }
            ],
            'responses': {
                201: {'description': '创建成功'}
            }
        }
    },
    'stockout': {
        'get_list': {
            'summary': '获取出货列表',
            'description': '获取所有出货单的列表',
            'responses': {
                200: {'description': '出货列表'}
            }
        },
        'create': {
            'summary': '创建出货',
            'description': '创建新的出货单',
            'parameters': [
                {
                    'name': 'body',
                    'in': 'body',
                    'required': True,
                    'schema': {
                        'type': 'object',
                        'required': ['product_id', 'quantity'],
                        'properties': {
                            'product_id': {'type': 'integer', 'description': '产品ID'},
                            'quantity': {'type': 'integer', 'description': '出货数量'},
                            'customer': {'type': 'string', 'description': '客户名称(可选)'}
                        }
                    }
                }
            ],
            'responses': {
                201: {'description': '创建成功'}
            }
        }
    }
}


if __name__ == '__main__':
    print("API文档配置模块")
    print("主要API端点:")
    for module, apis in API_DOCS.items():
        print(f"\n{module}:")
        for api_name in apis.keys():
            print(f"  - {api_name}")
