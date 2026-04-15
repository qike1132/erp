"""
暂存订单API路由
已迁移至 FastAPI: /api/v1/staging-orders/*
此文件仅保留Blueprint定义以维持注册兼容性
"""
from flask import Blueprint

staging_order_bp = Blueprint('staging_order', __name__)
