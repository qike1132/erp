"""
暂存出货API路由
已迁移至 FastAPI: /api/v1/staging-stockouts/*
此文件仅保留Blueprint定义以维持注册兼容性
"""
from flask import Blueprint

staging_stockout_bp = Blueprint('staging_stockout', __name__)
