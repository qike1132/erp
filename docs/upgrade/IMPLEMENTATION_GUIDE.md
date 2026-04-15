# ERP系统依赖库升级实施手册

**版本**: v1.0.0  
**日期**: 2026-04-09  
**状态**: 待执行  
**负责人**: 开发团队

---

## 目录

1. [升级概述](#1-升级概述)
2. [准备工作](#2-准备工作)
3. [阶段一: P0基础库集成](#3-阶段一-p0基础库集成)
4. [阶段二: P1功能增强](#4-阶段二-p1功能增强)
5. [阶段三: P2高级功能](#5-阶段三-p2高级功能)
6. [验证测试](#6-验证测试)
7. [问题处理](#7-问题处理)
8. [附录](#8-附录)

---

## 1. 升级概述

### 1.1 升级目标

| 目标 | 描述 |
|------|------|
| **数据质量提升** | 手机号验证、编码检测、格式化 |
| **搜索体验优化** | 拼音搜索、模糊匹配 |
| **报表能力增强** | 图表支持、多格式导出 |
| **安全性提升** | XSS防护、输入清理 |
| **性能优化** | 异步文件处理、高效解析 |

### 1.2 升级范围

| 类别 | 数量 | 优先级 |
|------|------|--------|
| P0 立即安装 | 12个 | 🔴 高 |
| P1 近期升级 | 8个 | 🟡 中 |
| P2 后续规划 | 7个 | 🟢 低 |

### 1.3 时间安排

| 阶段 | 时间 | 内容 |
|------|------|------|
| 阶段一 | 第1-2周 | P0基础库集成 |
| 阶段二 | 第3-4周 | P1功能增强 |
| 阶段三 | 第5-6周 | P2高级功能 |
| 阶段四 | 第7-8周 | 文档与上线 |

---

## 2. 准备工作

### 2.1 环境检查

```bash
# 检查Python版本 (要求 >= 3.9)
python --version

# 检查pip版本
pip --version

# 检查虚拟环境
pip list

# 检查磁盘空间 (至少5GB)
df -h

# 检查数据库连接
python -c "from app import db; print(db.engine.url)"
```

### 2.2 备份操作

```bash
# 创建备份目录
mkdir -p backups/upgrade_$(date +%Y%m%d)

# 备份虚拟环境
pip freeze > backups/upgrade_$(date +%Y%m%d)/requirements_backup.txt
tar -czf backups/upgrade_$(date +%Y%m%d)/venv_backup.tar.gz venv/

# 备份数据库
mysqldump -u root -p erp_system > backups/upgrade_$(date +%Y%m%d)/db_backup.sql

# 备份配置文件
cp .env backups/upgrade_$(date +%Y%m%d)/.env.backup
cp -r config backups/upgrade_$(date +%Y%m%d)/config_backup/

# 创建Git标签
git tag -a v1.0.0-pre-upgrade -m "升级前备份"
git push origin v1.0.0-pre-upgrade
```

### 2.3 创建升级分支

```bash
# 创建并切换到升级分支
git checkout -b feature/dependency-upgrade

# 推送到远程
git push origin feature/dependency-upgrade
```

---

## 3. 阶段一: P0基础库集成

### 3.1 安装P0依赖

```bash
# 激活虚拟环境
.\venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# 安装P0依赖
pip install chardet==5.2.0
pip install phonenumbers==8.13.27
pip install pypinyin==0.51.0
pip install python-slugify==8.0.4
pip install arrow==1.3.0
pip install python-dateutil==2.9.0
pip install PyYAML==6.0.1
pip install lxml==5.1.0
pip install beautifulsoup4==4.12.3
pip install bleach==6.1.0
pip install requests==2.31.0
pip install sqlparse==0.4.4

# 验证安装
pip list | grep -E "chardet|phonenumbers|pypinyin|arrow|lxml|bleach|requests"
```

### 3.2 集成chardet到批量导入

**文件**: `utils/batch_upload_utils.py`

```python
import chardet

def detect_file_encoding(file_path: str) -> str:
    """
    检测文件编码
    
    Args:
        file_path: 文件路径
        
    Returns:
        编码名称
    """
    with open(file_path, 'rb') as f:
        raw_data = f.read(10000)
        result = chardet.detect(raw_data)
        return result['encoding'] or 'utf-8'

def safe_read_excel(file_path: str):
    """
    安全读取Excel文件
    
    Args:
        file_path: 文件路径
        
    Returns:
        DataFrame
    """
    import pandas as pd
    
    try:
        return pd.read_excel(file_path)
    except UnicodeDecodeError:
        encoding = detect_file_encoding(file_path)
        return pd.read_excel(file_path, encoding=encoding)
```

### 3.3 集成phonenumbers到验证器

**文件**: `utils/validators.py`

```python
import phonenumbers
from phonenumbers.phonenumberutil import NumberParseException

class Validator:
    def validate_phone_international(self, value: str, field_name: str, 
                                      region: str = 'CN') -> tuple:
        """
        验证手机号 - 支持国际号码
        
        Args:
            value: 手机号字符串
            field_name: 字段名
            region: 国家代码
            
        Returns:
            (是否有效, 格式化后的号码)
        """
        try:
            parsed = phonenumbers.parse(value, region)
            if phonenumbers.is_valid_number(parsed):
                formatted = phonenumbers.format_number(
                    parsed, 
                    phonenumbers.PhoneNumberFormat.E164
                )
                return True, formatted
        except NumberParseException:
            pass
        
        self.errors[field_name] = f'{field_name}不是有效的手机号'
        return False, None
```

### 3.4 集成pypinyin到搜索

**文件**: `app/routes/api.py`

```python
from pypinyin import lazy_pinyin

@api_bp.route('/product-search')
@api_permission_required('product_view')
def product_search():
    """产品搜索 - 支持拼音搜索"""
    query = request.args.get('q', '').strip()
    
    if not query:
        return jsonify([])
    
    query_pinyin = ''.join(lazy_pinyin(query))
    query_abbr = ''.join([x[0] for x in lazy_pinyin(query)])
    
    products = Product.query.filter(
        db.or_(
            Product.name.contains(query),
            Product.barcode.contains(query),
            Product.name_pinyin.contains(query_pinyin) if hasattr(Product, 'name_pinyin') else False,
            Product.name_pinyin_abbr.contains(query_abbr) if hasattr(Product, 'name_pinyin_abbr') else False
        )
    ).limit(50).all()
    
    return jsonify([{
        'id': p.id,
        'name': p.name,
        'barcode': p.barcode,
        'current_stock': p.current_stock
    } for p in products])
```

### 3.5 集成arrow到日期处理

**文件**: `utils/date_utils.py` (新建)

```python
"""
日期处理工具模块
使用arrow库简化日期处理
"""
import arrow
from datetime import datetime
from typing import Tuple, Optional

def parse_date_flexible(date_str: str) -> Optional[datetime]:
    """
    灵活解析日期字符串
    
    支持格式:
    - 2024-01-15
    - 2024/01/15
    - 1月15日
    - 昨天、今天、明天
    
    Args:
        date_str: 日期字符串
        
    Returns:
        datetime对象
    """
    if not date_str:
        return None
    
    date_str = date_str.strip()
    
    try:
        if date_str in ['今天', '今日']:
            return arrow.now().datetime
        elif date_str in ['昨天', '昨日']:
            return arrow.now().shift(days=-1).datetime
        elif date_str in ['明天', '明日']:
            return arrow.now().shift(days=1).datetime
        else:
            return arrow.get(date_str).datetime
    except:
        return None

def get_date_range(period: str) -> Tuple[datetime, datetime]:
    """
    获取日期范围
    
    Args:
        period: 时间段标识 (today/week/month/quarter/year)
        
    Returns:
        (开始时间, 结束时间)
    """
    now = arrow.now()
    
    ranges = {
        'today': (now.floor('day'), now.ceil('day')),
        'yesterday': (now.shift(days=-1).floor('day'), now.shift(days=-1).ceil('day')),
        'week': (now.floor('week'), now.ceil('week')),
        'month': (now.floor('month'), now.ceil('month')),
        'quarter': (now.floor('quarter'), now.ceil('quarter')),
        'year': (now.floor('year'), now.ceil('year')),
    }
    
    if period in ranges:
        start, end = ranges[period]
        return start.datetime, end.datetime
    
    return now.floor('day').datetime, now.ceil('day').datetime

def format_date_human(dt: datetime) -> str:
    """
    人性化日期格式化
    
    Args:
        dt: datetime对象
        
    Returns:
        格式化字符串
    """
    return arrow.get(dt).humanize(locale='zh')
```

### 3.6 集成bleach到输入清理

**文件**: `utils/sanitizer.py` (新建)

```python
"""
输入清理工具模块
使用bleach防止XSS攻击
"""
import bleach
from typing import List, Optional

ALLOWED_TAGS = ['b', 'i', 'u', 'strong', 'em', 'br', 'p']
ALLOWED_ATTRIBUTES = {}

def sanitize_html(text: str, 
                  allowed_tags: Optional[List[str]] = None,
                  allowed_attributes: Optional[dict] = None) -> str:
    """
    清理HTML内容
    
    Args:
        text: 原始文本
        allowed_tags: 允许的HTML标签
        allowed_attributes: 允许的属性
        
    Returns:
        清理后的安全文本
    """
    if not text:
        return ''
    
    tags = allowed_tags or ALLOWED_TAGS
    attrs = allowed_attributes or ALLOWED_ATTRIBUTES
    
    return bleach.clean(
        text,
        tags=tags,
        attributes=attrs,
        strip=True
    )

def sanitize_plain_text(text: str) -> str:
    """
    清理纯文本 (移除所有HTML)
    
    Args:
        text: 原始文本
        
    Returns:
        纯文本
    """
    if not text:
        return ''
    
    return bleach.clean(text, tags=[], strip=True)

def sanitize_url(url: str) -> str:
    """
    清理URL
    
    Args:
        url: URL字符串
        
    Returns:
        安全的URL
    """
    if not url:
        return ''
    
    return bleach.clean(url, tags=[], attributes={}, strip=True)
```

### 3.7 P0阶段验证

```bash
# 运行单元测试
pytest tests/test_new_libraries.py -v

# 运行集成测试
pytest tests/test_integration.py -v

# 检查代码质量
flake8 utils/ app/routes/
black --check utils/ app/routes/

# 启动服务验证
python run.py
# 访问 http://localhost:5003/api/health
```

---

## 4. 阶段二: P1功能增强

### 4.1 安装P1依赖

```bash
pip install XlsxWriter==3.1.9
pip install python-docx==1.1.0
pip install PyPDF2==3.0.1
pip install aiofiles==23.2.1
pip install watchdog==3.0.0
pip install fuzzywuzzy==0.18.0
pip install python-Levenshtein==0.25.1
```

### 4.2 集成XlsxWriter优化报表

**文件**: `utils/report_exporter_xlsxwriter.py` (新建)

```python
"""
报表导出工具 - XlsxWriter版本
性能优于openpyxl，支持图表
"""
import xlsxwriter
from io import BytesIO
from typing import List, Dict, Any

class XlsxWriterExporter:
    """XlsxWriter报表导出器"""
    
    def __init__(self):
        self.header_format = {
            'bold': True,
            'bg_color': '#4472C4',
            'font_color': 'white',
            'border': 1
        }
    
    def export_with_chart(self, data: List[Dict], 
                          title: str,
                          chart_type: str = 'column') -> bytes:
        """
        导出带图表的Excel
        
        Args:
            data: 数据列表
            title: 标题
            chart_type: 图表类型
            
        Returns:
            Excel文件字节
        """
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet(title)
        
        header_format = workbook.add_format(self.header_format)
        
        if data:
            headers = list(data[0].keys())
            for col, header in enumerate(headers):
                worksheet.write(0, col, header, header_format)
            
            for row_idx, row_data in enumerate(data, start=1):
                for col, key in enumerate(headers):
                    worksheet.write(row_idx, col, row_data.get(key, ''))
        
        if len(data) > 1 and chart_type:
            chart = workbook.add_chart({'type': chart_type})
            chart.add_series({
                'name': f'={title}!$B$1',
                'categories': f'={title}!$A$2:$A${len(data)+1}',
                'values': f'={title}!$B$2:$B${len(data)+1}'
            })
            worksheet.insert_chart('E2', chart)
        
        workbook.close()
        output.seek(0)
        return output.getvalue()
```

### 4.3 集成fuzzywuzzy模糊搜索

**文件**: `utils/fuzzy_search.py` (新建)

```python
"""
模糊搜索工具模块
"""
from fuzzywuzzy import fuzz, process
from typing import List, Tuple, Any

class FuzzySearcher:
    """模糊搜索器"""
    
    def __init__(self, items: List[Any], key_func=None):
        """
        初始化
        
        Args:
            items: 搜索项列表
            key_func: 提取搜索键的函数
        """
        self.items = items
        self.key_func = key_func or (lambda x: str(x))
        self.choices = {i: self.key_func(item) for i, item in enumerate(items)}
    
    def search(self, query: str, threshold: int = 70, 
               limit: int = 10) -> List[Tuple[Any, int]]:
        """
        模糊搜索
        
        Args:
            query: 搜索词
            threshold: 相似度阈值
            limit: 返回数量限制
            
        Returns:
            [(匹配项, 相似度), ...]
        """
        results = process.extract(
            query, 
            self.choices, 
            limit=limit,
            scorer=fuzz.WRatio
        )
        
        return [(self.items[r[2]], r[1]) for r in results if r[1] >= threshold]
    
    def find_duplicates(self, threshold: int = 90) -> List[Tuple[Any, Any, int]]:
        """
        查找重复项
        
        Args:
            threshold: 相似度阈值
            
        Returns:
            [(项1, 项2, 相似度), ...]
        """
        duplicates = []
        keys = list(self.choices.keys())
        
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                score = fuzz.ratio(
                    self.choices[keys[i]], 
                    self.choices[keys[j]]
                )
                if score >= threshold:
                    duplicates.append((
                        self.items[keys[i]],
                        self.items[keys[j]],
                        score
                    ))
        
        return duplicates
```

### 4.4 P1阶段验证

```bash
# 运行P1测试
pytest tests/test_p1_features.py -v

# 性能测试
pytest tests/performance/test_performance.py -v

# 代码覆盖率
pytest --cov=utils --cov=app tests/
```

---

## 5. 阶段三: P2高级功能

### 5.1 安装P2依赖

```bash
pip install flashtext==2.7
pip install tablib==3.6.1
pip install aiohttp==3.9.3
pip install websockets==12.0
pip install ReportLab==4.0.8
pip install pdfminer.six==20231228
pip install python-qrcode==7.4.2
```

### 5.2 P2功能集成

根据业务需求按需集成，详见 `DEPENDENCY_GUIDE.md`

### 5.3 P2阶段验证

```bash
# 全面回归测试
pytest tests/ -v --cov=app --cov=utils

# 安全扫描
bandit -r app/ utils/

# 性能基准测试
pytest tests/performance/ -v
```

---

## 6. 验证测试

### 6.1 功能验证清单

```
□ 用户登录功能正常
□ 产品列表加载正常
□ 产品搜索功能正常 (拼音搜索)
□ 订单创建功能正常
□ 订单状态流转正常
□ 批量导入功能正常 (编码检测)
□ 批量导出功能正常
□ 报表生成功能正常
□ 客户管理功能正常 (手机号验证)
□ 库存管理功能正常
□ API接口响应正常
□ 缓存功能正常
```

### 6.2 性能验证指标

| 指标 | 基准值 | 目标值 | 实际值 |
|------|--------|--------|--------|
| 产品搜索响应时间 | <200ms | <100ms | ___ |
| 批量导入10000行 | <15s | <10s | ___ |
| 报表导出1000行 | <5s | <3s | ___ |
| API平均响应时间 | <100ms | <80ms | ___ |

### 6.3 安全验证

```bash
# 运行安全扫描
bandit -r app/ utils/ -f json -o security_report.json

# 检查依赖漏洞
pip-audit

# 检查敏感信息
detect-secrets scan app/ > secrets_report.json
```

---

## 7. 问题处理

### 7.1 常见问题

#### Q1: pip安装依赖冲突

```bash
# 解决方案
pip install pip-tools
pip-compile requirements.upgrade.txt --output-file requirements.lock.txt
pip-sync requirements.lock.txt
```

#### Q2: 导入模块失败

```bash
# 检查模块
python -c "import phonenumbers; print(phonenumbers.__version__)"

# 重新安装
pip uninstall phonenumbers
pip install phonenumbers==8.13.27
```

#### Q3: 编码问题

```bash
# 设置环境变量
export PYTHONIOENCODING=utf-8
export LANG=en_US.UTF-8
```

### 7.2 回滚操作

详见 `scripts/upgrade/rollback.py`

---

## 8. 附录

### 8.1 命令清单

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
.\venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.upgrade.txt

# 运行测试
pytest tests/ -v

# 启动服务
python run.py

# 查看依赖树
pipdeptree

# 检查依赖冲突
pip check
```

### 8.2 配置文件

`.env` 新增配置:

```env
# 新增配置项
ENABLE_PINYIN_SEARCH=true
ENABLE_FUZZY_SEARCH=true
PHONE_DEFAULT_REGION=CN
```

### 8.3 联系人列表

| 角色 | 姓名 | 联系方式 |
|------|------|----------|
| 项目负责人 | ___ | ___ |
| 开发负责人 | ___ | ___ |
| 测试负责人 | ___ | ___ |
| 运维负责人 | ___ | ___ |

---

**文档状态**: 待执行  
**最后更新**: 2026-04-09
