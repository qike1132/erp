# ERP系统依赖库说明文档

**版本**: v2.0.0  
**日期**: 2026-04-09  
**状态**: 待集成

---

## 目录

1. [P0 核心依赖库](#1-p0-核心依赖库)
2. [P1 功能增强库](#2-p1-功能增强库)
3. [P2 高级功能库](#3-p2-高级功能库)
4. [依赖冲突解决](#4-依赖冲突解决)
5. [最佳实践](#5-最佳实践)

---

## 1. P0 核心依赖库

### 1.1 chardet - 字符编码检测器

| 属性 | 值 |
|------|-----|
| **版本** | 5.2.0 |
| **优先级** | P0 |
| **引入原因** | 解决Excel/CSV导入时的编码乱码问题 |
| **官方文档** | https://chardet.readthedocs.io/ |

**使用场景**:
- 批量导入Excel文件时自动检测编码
- 处理用户上传的未知编码文本文件
- 数据迁移时的编码转换

**代码示例**:
```python
import chardet

def detect_file_encoding(file_path: str) -> str:
    """检测文件编码"""
    with open(file_path, 'rb') as f:
        raw_data = f.read(10000)
        result = chardet.detect(raw_data)
        return result.get('encoding', 'utf-8')

# 在批量导入中使用
encoding = detect_file_encoding(uploaded_file.path)
df = pd.read_excel(uploaded_file.path, encoding=encoding)
```

**集成文件**:
- `utils/batch_upload_utils.py`
- `utils/file_utils.py`

**注意事项**:
- 检测大文件时建议只读取前10KB
- 检测结果包含confidence字段，低于0.7时建议提示用户

---

### 1.2 phonenumbers - 电话号码验证

| 属性 | 值 |
|------|-----|
| **版本** | 8.13.27 |
| **优先级** | P0 |
| **引入原因** | 客户/供应商手机号验证和格式化 |
| **官方文档** | https://github.com/daviddrysdale/python-phonenumbers |

**使用场景**:
- 客户信息管理中的手机号验证
- 供应商联系方式格式化
- 国际业务电话处理

**代码示例**:
```python
import phonenumbers
from phonenumbers.phonenumberutil import NumberParseException

def validate_and_format_phone(phone_str: str, region: str = 'CN') -> tuple:
    """
    验证并格式化手机号
    
    Returns:
        (是否有效, 格式化后的号码, 错误信息)
    """
    try:
        parsed = phonenumbers.parse(phone_str, region)
        if phonenumbers.is_valid_number(parsed):
            formatted = phonenumbers.format_number(
                parsed, 
                phonenumbers.PhoneNumberFormat.E164
            )
            return True, formatted, None
        return False, None, "无效的手机号"
    except NumberParseException as e:
        return False, None, str(e)

# 使用示例
valid, phone, error = validate_and_format_phone("13812345678")
# valid=True, phone="+8613812345678"
```

**集成文件**:
- `utils/validators.py`
- `app/models/customer.py`
- `app/models/supplier.py`

**注意事项**:
- 默认地区设置为CN（中国大陆）
- E164格式是国际标准格式，便于存储和比较

---

### 1.3 pypinyin - 汉字拼音转换

| 属性 | 值 |
|------|-----|
| **版本** | 0.51.0 |
| **优先级** | P0 |
| **引入原因** | 支持产品/客户拼音搜索 |
| **官方文档** | https://github.com/mozillazg/python-pinyin |

**使用场景**:
- 产品名称拼音搜索
- 客户姓名拼音索引
- 生成拼音首字母快捷查询

**代码示例**:
```python
from pypinyin import lazy_pinyin, pinyin, Style

def get_pinyin(text: str) -> str:
    """获取拼音（不带声调）"""
    return ''.join(lazy_pinyin(text))

def get_pinyin_abbr(text: str) -> str:
    """获取拼音首字母"""
    return ''.join([x[0] for x in lazy_pinyin(text)])

def get_pinyin_with_tone(text: str) -> list:
    """获取拼音（带声调）"""
    return pinyin(text, style=Style.TONE)

# 使用示例
get_pinyin("苹果手机")  # "pingguoshouji"
get_pinyin_abbr("苹果手机")  # "pgsj"
```

**集成文件**:
- `app/routes/api.py` - 产品搜索
- `app/routes/customer.py` - 客户搜索
- `utils/search_utils.py`

**数据库字段建议**:
```python
class Product(db.Model):
    name = db.Column(db.String(100))
    name_pinyin = db.Column(db.String(200))  # 全拼
    name_pinyin_abbr = db.Column(db.String(50))  # 首字母
```

**注意事项**:
- 多音字可能需要自定义词典
- 建议在保存时预计算拼音字段

---

### 1.4 python-slugify - Slug生成器

| 属性 | 值 |
|------|-----|
| **版本** | 8.0.4 |
| **优先级** | P0 |
| **引入原因** | 自动生成产品编码、URL友好名称 |
| **官方文档** | https://github.com/un33k/python-slugify |

**使用场景**:
- 产品编码自动生成
- URL友好名称生成
- 文件名规范化

**代码示例**:
```python
from slugify import slugify

def generate_product_code(name: str, category: str = None) -> str:
    """生成产品编码"""
    base = slugify(name, separator='_').upper()
    if category:
        base = f"{slugify(category, separator='_').upper()}_{base}"
    return base[:30]

# 使用示例
generate_product_code("苹果 iPhone 15 Pro")  # "APPLE_IPHONE_15_PRO"
generate_product_code("苹果 iPhone 15 Pro", "手机")  # "SHOUJI_APPLE_IPHONE_15_PRO"
```

**集成文件**:
- `app/routes/product.py`
- `app/routes/customer.py`

---

### 1.5 arrow - 日期时间处理

| 属性 | 值 |
|------|-----|
| **版本** | 1.3.0 |
| **优先级** | P0 |
| **引入原因** | 简化日期处理代码，支持人性化日期解析 |
| **官方文档** | https://arrow.readthedocs.io/ |

**使用场景**:
- 报表日期范围计算
- 订单日期处理
- 人性化日期显示

**代码示例**:
```python
import arrow

def parse_date_flexible(date_str: str):
    """灵活解析日期"""
    if not date_str:
        return None
    
    # 支持多种格式
    # "2024-01-15", "2024/01/15", "1月15日", "昨天", "今天"
    try:
        return arrow.get(date_str).datetime
    except:
        return None

def get_date_range(period: str):
    """获取日期范围"""
    now = arrow.now()
    
    ranges = {
        'today': (now.floor('day'), now.ceil('day')),
        'week': (now.floor('week'), now.ceil('week')),
        'month': (now.floor('month'), now.ceil('month')),
        'quarter': (now.floor('quarter'), now.ceil('quarter')),
        'year': (now.floor('year'), now.ceil('year')),
    }
    
    if period in ranges:
        start, end = ranges[period]
        return start.datetime, end.datetime
    return None, None

def format_human(dt):
    """人性化日期显示"""
    return arrow.get(dt).humanize(locale='zh')

# 使用示例
format_human(datetime.now() - timedelta(days=1))  # "1天前"
```

**集成文件**:
- `utils/date_utils.py`
- `app/routes/report.py`
- `app/routes/order.py`

---

### 1.6 python-dateutil - 日期扩展

| 属性 | 值 |
|------|-----|
| **版本** | 2.9.0 |
| **优先级** | P0 |
| **引入原因** | 复杂日期计算、相对日期处理 |
| **官方文档** | https://dateutil.readthedocs.io/ |

**使用场景**:
- 月末日期计算
- 工作日计算
- 周期性报表日期生成

**代码示例**:
```python
from dateutil.relativedelta import relativedelta
from dateutil.rrule import rrule, MONTHLY, WEEKLY
from datetime import datetime

def get_last_day_of_month(dt: datetime) -> datetime:
    """获取月末日期"""
    return dt + relativedelta(day=31)

def add_months(dt: datetime, months: int) -> datetime:
    """增加月份（正确处理月末）"""
    return dt + relativedelta(months=months)

def get_next_n_months(n: int):
    """获取未来N个月的月份列表"""
    start = datetime.now().replace(day=1)
    return list(rrule(MONTHLY, dtstart=start, count=n))

# 使用示例
add_months(datetime(2024, 1, 31), 1)  # 2024-02-29（正确处理）
```

**集成文件**:
- `utils/date_utils.py`
- `app/routes/report.py`

---

### 1.7 lxml - HTML/XML解析

| 属性 | 值 |
|------|-----|
| **版本** | 5.1.0 |
| **优先级** | P0 |
| **引入原因** | 高性能HTML/XML解析 |
| **官方文档** | https://lxml.de/ |

**使用场景**:
- 外部HTML内容解析
- XML接口对接
- 数据导入解析

**代码示例**:
```python
from lxml import etree

def parse_html_table(html_content: str):
    """解析HTML表格"""
    tree = etree.HTML(html_content)
    tables = tree.xpath('//table')
    
    data = []
    for table in tables:
        rows = table.xpath('.//tr')
        for row in rows:
            cells = row.xpath('.//td/text()')
            data.append(cells)
    return data

def parse_xml_config(xml_content: str):
    """解析XML配置"""
    root = etree.fromstring(xml_content.encode())
    return {elem.tag: elem.text for elem in root.xpath('//*')}
```

**集成文件**:
- `utils/xml_parser.py`
- `utils/html_parser.py`

**注意事项**:
- Windows安装可能需要预编译包
- 性能比BeautifulSoup快10倍以上

---

### 1.8 beautifulsoup4 - HTML解析

| 属性 | 值 |
|------|-----|
| **版本** | 4.12.3 |
| **优先级** | P0 |
| **引入原因** | 简化HTML解析，容错性强 |
| **官方文档** | https://www.crummy.com/software/BeautifulSoup/bs4/doc/ |

**代码示例**:
```python
from bs4 import BeautifulSoup

def extract_text_from_html(html_content: str) -> str:
    """从HTML提取纯文本"""
    soup = BeautifulSoup(html_content, 'lxml')
    return soup.get_text(strip=True)

def extract_links(html_content: str) -> list:
    """提取所有链接"""
    soup = BeautifulSoup(html_content, 'lxml')
    return [a.get('href') for a in soup.find_all('a', href=True)]
```

---

### 1.9 bleach - XSS防护

| 属性 | 值 |
|------|-----|
| **版本** | 6.1.0 |
| **优先级** | P0 |
| **引入原因** | 防止XSS攻击，清理用户输入 |
| **官方文档** | https://bleach.readthedocs.io/ |

**使用场景**:
- 用户输入HTML清理
- 富文本备注处理
- XSS攻击防护

**代码示例**:
```python
import bleach

ALLOWED_TAGS = ['b', 'i', 'u', 'strong', 'em', 'br', 'p']
ALLOWED_ATTRIBUTES = {}

def sanitize_html(text: str) -> str:
    """清理HTML内容"""
    if not text:
        return ''
    return bleach.clean(text, tags=ALLOWED_TAGS, 
                       attributes=ALLOWED_ATTRIBUTES, strip=True)

def sanitize_plain_text(text: str) -> str:
    """清理纯文本（移除所有HTML）"""
    if not text:
        return ''
    return bleach.clean(text, tags=[], strip=True)

# 使用示例
sanitize_html('<script>alert(1)</script><b>安全</b>')  # "<b>安全</b>"
```

**集成文件**:
- `utils/sanitizer.py`
- `app/routes/order.py` - 备注字段
- `app/routes/customer.py` - 备注字段

---

### 1.10 requests - HTTP请求

| 属性 | 值 |
|------|-----|
| **版本** | 2.31.0 |
| **优先级** | P0 |
| **引入原因** | 外部API调用基础库 |
| **官方文档** | https://requests.readthedocs.io/ |

**使用场景**:
- 支付接口对接
- 物流系统对接
- 第三方API调用

**代码示例**:
```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def create_session():
    """创建带重试机制的HTTP会话"""
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, 
                  status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

def call_external_api(url: str, timeout: int = 10):
    """调用外部API"""
    session = create_session()
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()
```

---

### 1.11 sqlparse - SQL格式化

| 属性 | 值 |
|------|-----|
| **版本** | 0.4.4 |
| **优先级** | P0 |
| **引入原因** | SQL语句格式化、调试辅助 |
| **官方文档** | https://sqlparse.readthedocs.io/ |

**代码示例**:
```python
import sqlparse

def format_sql(sql: str) -> str:
    """格式化SQL语句"""
    return sqlparse.format(sql, reindent=True, keyword_case='upper')

# 使用示例
sql = "select * from product where name like '%苹果%'"
print(format_sql(sql))
# SELECT *
# FROM product
# WHERE name LIKE '%苹果%'
```

---

## 2. P1 功能增强库

### 2.1 XlsxWriter - Excel生成

| 属性 | 值 |
|------|-----|
| **版本** | 3.1.9 |
| **优先级** | P1 |
| **引入原因** | 高性能Excel报表生成，支持图表 |
| **官方文档** | https://xlsxwriter.readthedocs.io/ |

**与openpyxl对比**:
| 特性 | XlsxWriter | openpyxl |
|------|------------|----------|
| 创建速度 | 快 | 中 |
| 图表支持 | ✅ | ✅ |
| 读取Excel | ❌ | ✅ |
| 内存占用 | 低 | 中 |

**代码示例**:
```python
import xlsxwriter
from io import BytesIO

def export_report_with_chart(data: list, title: str) -> bytes:
    """导出带图表的Excel"""
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet(title)
    
    # 写入数据
    for row_idx, row in enumerate(data):
        for col_idx, value in enumerate(row):
            worksheet.write(row_idx, col_idx, value)
    
    # 创建图表
    chart = workbook.add_chart({'type': 'column'})
    chart.add_series({'values': f'={title}!$B$2:$B${len(data)+1}'})
    worksheet.insert_chart('E2', chart)
    
    workbook.close()
    output.seek(0)
    return output.getvalue()
```

---

### 2.2 python-docx - Word文档生成

| 属性 | 值 |
|------|-----|
| **版本** | 1.1.0 |
| **优先级** | P1 |
| **引入原因** | 生成Word格式合同、确认单 |
| **官方文档** | https://python-docx.readthedocs.io/ |

**代码示例**:
```python
from docx import Document
from docx.shared import Pt, Cm

def generate_contract(order) -> bytes:
    """生成订单合同"""
    doc = Document()
    
    doc.add_heading('销售合同', 0)
    doc.add_paragraph(f'合同编号：{order.order_no}')
    doc.add_paragraph(f'客户名称：{order.customer.name}')
    
    # 添加表格
    table = doc.add_table(rows=1, cols=4)
    table.style = 'Table Grid'
    
    # 保存到内存
    from io import BytesIO
    output = BytesIO()
    doc.save(output)
    output.seek(0)
    return output.getvalue()
```

---

### 2.3 fuzzywuzzy - 模糊搜索

| 属性 | 值 |
|------|-----|
| **版本** | 0.18.0 |
| **优先级** | P1 |
| **引入原因** | 产品/客户模糊搜索 |
| **官方文档** | https://github.com/seatgeek/fuzzywuzzy |

**代码示例**:
```python
from fuzzywuzzy import fuzz, process

def fuzzy_search_products(query: str, products: list, threshold: int = 70):
    """模糊搜索产品"""
    choices = {p.id: p.name for p in products}
    results = process.extract(query, choices, limit=10)
    return [products[r[2]] for r in results if r[1] >= threshold]

# 使用示例
fuzzy_search_products("苹果手机", products)  # 可匹配"苹果iPhone手机"
```

---

### 2.4 aiofiles - 异步文件操作

| 属性 | 值 |
|------|-----|
| **版本** | 23.2.1 |
| **优先级** | P1 |
| **引入原因** | 异步文件IO，提升性能 |
| **官方文档** | https://github.com/Tinche/aiofiles |

**代码示例**:
```python
import aiofiles
import asyncio

async def async_save_file(file_path: str, content: str):
    """异步保存文件"""
    async with aiofiles.open(file_path, 'w') as f:
        await f.write(content)

async def batch_save_files(files: list):
    """批量异步保存"""
    tasks = [async_save_file(f['path'], f['content']) for f in files]
    await asyncio.gather(*tasks)
```

---

### 2.5 watchdog - 文件监控

| 属性 | 值 |
|------|-----|
| **版本** | 3.0.0 |
| **优先级** | P1 |
| **引入原因** | 监控上传目录，自动处理新文件 |
| **官方文档** | https://python-watchdog.readthedocs.io/ |

**代码示例**:
```python
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class UploadHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.src_path.endswith('.xlsx'):
            auto_import_excel(event.src_path)

def start_file_watcher(path: str):
    observer = Observer()
    observer.schedule(UploadHandler(), path=path, recursive=False)
    observer.start()
```

---

## 3. P2 高级功能库

### 3.1 aiohttp - 异步HTTP

| 属性 | 值 |
|------|-----|
| **版本** | 3.9.3 |
| **优先级** | P2 |
| **引入原因** | 异步HTTP请求 |

### 3.2 ReportLab - PDF生成

| 属性 | 值 |
|------|-----|
| **版本** | 4.0.8 |
| **优先级** | P2 |
| **引入原因** | 复杂PDF报表生成 |

### 3.3 python-qrcode - 二维码生成

| 属性 | 值 |
|------|-----|
| **版本** | 7.4.2 |
| **优先级** | P2 |
| **引入原因** | 产品二维码、订单二维码生成 |

---

## 4. 依赖冲突解决

### 4.1 常见冲突

| 冲突库 | 解决方案 |
|--------|----------|
| lxml vs beautifulsoup4 | 同时安装，BeautifulSoup使用lxml解析器 |
| arrow vs python-dateutil | arrow依赖dateutil，自动安装 |
| fuzzywuzzy vs Levenshtein | 同时安装，Levenshtein加速fuzzywuzzy |

### 4.2 版本锁定

```bash
# 使用pip-tools锁定版本
pip install pip-tools
pip-compile requirements.upgrade.txt --output-file requirements.lock.txt
pip-sync requirements.lock.txt
```

---

## 5. 最佳实践

### 5.1 导入规范

```python
# 推荐：按标准库、第三方库、本地模块分组
import os
import sys

import phonenumbers
import arrow
from pypinyin import lazy_pinyin

from app import db
from utils.validators import Validator
```

### 5.2 错误处理

```python
import chardet

def safe_detect_encoding(file_path: str) -> str:
    """安全检测编码"""
    try:
        with open(file_path, 'rb') as f:
            result = chardet.detect(f.read(10000))
            return result.get('encoding', 'utf-8')
    except Exception as e:
        logging.error(f"编码检测失败: {e}")
        return 'utf-8'  # 返回默认编码
```

### 5.3 性能优化

```python
# 预计算拼音字段
from pypinyin import lazy_pinyin

def save_product(product):
    """保存产品时预计算拼音"""
    product.name_pinyin = ''.join(lazy_pinyin(product.name))
    product.name_pinyin_abbr = ''.join([x[0] for x in lazy_pinyin(product.name)])
    db.session.commit()
```

---

**文档状态**: 待集成  
**最后更新**: 2026-04-09
