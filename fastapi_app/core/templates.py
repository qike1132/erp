"""
Jinja2 模板引擎实例

集中管理 templates 实例，避免 main.py ↔ pages.py 循环导入。
main.py 和 pages.py 均从此模块导入 templates。
"""
from fastapi.templating import Jinja2Templates
import os

_templates_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=_templates_dir)
