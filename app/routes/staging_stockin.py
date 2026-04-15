"""
暂存备货API路由
已迁移至 FastAPI: /api/v1/staging-stockins/*
此文件仅保留Blueprint定义以维持注册兼容性
"""
from flask import Blueprint

staging_stockin_bp = Blueprint('staging_stockin', __name__)
