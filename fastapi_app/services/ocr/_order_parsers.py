"""订单 OCR 文本解析（聊天截图 / 表格截图）

与 `_text_parsers`（出货单专用）分开，原因有三：

1. **量词**：出货单解析器不认「10箱」，其行尾正则要求纯数字结尾；
2. **空格被吞**：OCR 会把「儿童保温杯500ml 50箱」输出成「儿童保温杯500ml50箱」，
   所以不能靠空格切分字段；
3. **名称含数字**：500ml / 8骨 / 三层 都是名称的一部分，数量必须是**行尾**那个数，
   否则「儿童保温杯500ml」会被拆成 名称=儿童保温杯 + 数量=500。

客户只从显式写法（「客户：X」或「X公司/集团/科技/有限」）提取。
聊天里的「张三：」**不**当客户——张三未必是 ERP 里的客户，宁可留空由前端用
表单已选客户兜底（对应需求「无法识别到客户信息时给替代方案」）。
"""
import re
from collections import Counter
from itertools import pairwise

from fastapi_app.services.ocr._text_parsers import (
    _extract_customer_from_header,
    _parse_quantity,
    _parse_table_format,
)

# 量词白名单。
#
# ⚠️ 刻意不含 ml / g / cm / 寸 这类规格后缀：它们是**产品名的一部分**，
#    一旦当成量词，「儿童保温杯500ml」会被拆成 名称=儿童保温杯 + 数量=500。
#    （正则要求量词紧跟数字且位于行尾，因此「保温杯」里的「杯」不会被误吃。）
UNITS = frozenset([
    '箱', '件', '个', '包', '袋', '盒', '条', '只', '支', '瓶', '桶', '套',
    '张', '把', '台', '根', '卷', '双', '斤', '公斤', '克', '米', '打',
    '组', '板', '提', '罐', '听', '杯', '盘', '筒', '片', '扎', '捆',
    '本', '份', '册', '束', '串', '堆', '粒', '颗', '副', '幅', '叠', '摞',
])

_UNIT_ALT = '|'.join(sorted(UNITS, key=len, reverse=True))

# 行内条目的权威形状：名称 + 数量 + 可选量词。
#
# 分两条正则，按「先带空格、后紧凑」的顺序试：
#
# 1. `_ITEM_RE_SPACED`：名称与数量之间有空白 → 边界明确，**名称允许以数字结尾**
#    （`文件夹A4 100个`）。旧实现只留紧凑版，会把这类整行丢掉。
# 2. `_ITEM_RE_TIGHT`：无空白（OCR 常把空格吞掉）→ 名称必须以**非数字、非点、非空白**
#    结尾，这一条同时挡住两类脏数据：「卡通雨伞8骨 1.5.5箱」这种畸形数量，
#    以及把「500ml」的 500 误当数量。
#
# ⚠️ 无空白时「名称尾部的数字」与「数量」本质上是歧义的：`文件夹A4100个` 既可读成
#    A4+100 也可读成 A4100 整体。此处取**贪婪**读法（数量=4100）并保留该行为；
#    要消除歧义只能靠带空格的输入。
#
# 乘号只在紧跟数字时才认：`[×*]` 后可有空格，但 `[xX]` 必须紧跟数字，
# 否则 `iPhone X 100台` 的型号尾巴 X 会被当成乘号吃掉。
_ITEM_RE_SPACED = re.compile(
    rf'^(?P<name>.+?)\s+(?P<qty>\d+(?:\.\d+)?)\s*(?:(?P<unit>{_UNIT_ALT}))?\s*$'
)
_ITEM_RE_TIGHT = re.compile(
    rf'^(?P<name>.+?[^\d.\s])\s*(?:(?:[×*]\s*)|(?:[xX](?=\d)))?(?P<qty>\d+(?:\.\d+)?)\s*'
    rf'(?:(?P<unit>{_UNIT_ALT}))?\s*$'
)

# 产品列的**明确**列名。表头判定与列角色判定共用这一份，避免三处别名表各写一遍后漂移
# （早先 `商品名称` 只写进了其中一处，另一处就看不见它）。
_STRICT_PRODUCT_LABELS = ('产品名称', '商品名称', '物料名称', '品名', '货品')
# 宽松别名：聊天里「产品明细」这类字眼也会命中，因此只用于**列角色**判定，不用于表头准入
_LOOSE_PRODUCT_LABELS = ('产品', '商品', '物料')

# 表头列角色。一行命中哪组关键词就是哪一列；命中不了的列算 other，**仍然占一列**。
# 顺序即判定优先级（「客户名称」要排在「名称」类之前，否则会被误判为产品列）。
_HEADER_ROLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('customer', ('客户名称', '客户', '收货单位', '收货', '买方', '采购方')),
    ('product_name', _STRICT_PRODUCT_LABELS + _LOOSE_PRODUCT_LABELS),
    ('quantity', ('订单数量', '订购数量', '下单数量', '数量合计', '数量', '数目', '数', 'qty')),
    ('unit', ('单位', '量词')),
    ('note', ('备注', '说明', '摘要')),
    ('other', ('序号', '规格', '型号', '单价', '金额', '总价', '货号', '条码', '日期', '时间')),
)

# 表格路径的准入条件：必须出现**明确**产品词。
# 用「产品名称/品名/货品」而非「产品」——聊天里「产品明细」这类字眼会误触发表头判定。
_TABLE_HEADER_RE = re.compile('|'.join(_STRICT_PRODUCT_LABELS))

# 聊天里的发送者前缀：短、无数字。客户/收货/买方不在此列（它们是客户字段的载体）
_SENDER_RE = re.compile(r'^([^\d：:]{1,12})[：:]\s*(.+)$')
_CUSTOMER_LABELS = ('客户', '收货', '买方', '采购')

# 明确的噪音：系统消息与状态标记
_NOISE_RE = re.compile(r'(撤回|已读|未读|\[图片\]|\[表情\]|\[链接\]|\[语音\]|拍了拍|消息已发出)')

# 日期/单号形状。缺了这条，「订货单2026-09-29」会被行尾正则读成 名称=订货单2026-09-、数量=29。
#
# ⚠️ 分隔符**不能含小数点**：早先写成 `[-/年.]`，结果「凉席1.8m 20条」「保温杯2.5L 10个」
#    里的小数规格被判成日期，整行被丢掉。日期必须有 4 位年份，或无年份的 `MM-DD` 两段式。
_DATE_RE = re.compile(r'(\d{4}\s*[-/年]\s*\d{1,2}(\s*[-/月]\s*\d{1,2})?)|(\d{1,2}\s*[-/]\s*\d{1,2})')

# 一行里塞多个条目时的分隔符（不切 '/'，产品名里可能带斜杠）
_SEP_RE = re.compile(r'[、，,;；]')

_FULLWIDTH = str.maketrans({
    '０': '0', '１': '1', '２': '2', '３': '3', '４': '4',
    '５': '5', '６': '6', '７': '7', '８': '8', '９': '9',
    '：': ':', '，': ',', '；': ';',
})


def _normalize(text: str) -> str:
    return text.translate(_FULLWIDTH)


def _strip_sender(line: str) -> str:
    """去掉「张三：」这类发送者前缀，但保留「客户：」——后者是客户字段本身"""
    m = _SENDER_RE.match(line)
    if not m:
        return line
    prefix = m.group(1).strip()
    if any(prefix.startswith(label) for label in _CUSTOMER_LABELS):
        return line
    return m.group(2).strip()


def _is_name_like(name: str) -> bool:
    """名称至少 2 个字符，且含中文或字母（纯数字/符号串不是产品名）"""
    return len(name) >= 2 and bool(re.search(r'[一-龥a-zA-Z]', name))


def _match_item(segment: str) -> re.Match | None:
    """先试「带空格」形态（边界明确），再试紧凑形态（OCR 吞了空格）"""
    return _ITEM_RE_SPACED.match(segment) or _ITEM_RE_TIGHT.match(segment)


def _parse_order_lines(lines: list[str]) -> list[dict]:
    """聊天/自由文本形态：逐行、按分隔符拆段、取行尾数量"""
    items = []
    for raw in lines:
        if _NOISE_RE.search(raw) or _DATE_RE.search(raw):
            continue
        for segment in _SEP_RE.split(raw):
            segment = _strip_sender(segment.strip())
            if not segment:
                continue
            match = _match_item(segment)
            if not match:
                continue
            name = match.group('name').strip(' -·—:：')
            quantity = _parse_quantity(match.group('qty'))
            if quantity <= 0 or not _is_name_like(name):
                continue
            items.append({
                'product_name': name,
                'quantity': quantity,
                'unit': match.group('unit') or '',
                'customer': '',
                'note': '',
            })
    return items


def _from_table_item(item: dict) -> dict | None:
    """表格路径产出的条目归一化：把其实是量词的备注挪到 unit（本轮不提取备注）"""
    name = str(item.get('product_name', '')).strip()
    quantity = _parse_quantity(str(item.get('quantity', 0)))
    if quantity <= 0 or not _is_name_like(name):
        return None
    note = str(item.get('note', '')).strip()
    unit = note if note in UNITS else ''
    return {
        'product_name': name,
        'quantity': quantity,
        'unit': unit,
        'customer': str(item.get('customer', '')).strip(),
        'note': '',
    }


def _from_table_items(parsed: list[dict]) -> list[dict]:
    result = []
    for item in parsed:
        normalized = _from_table_item(item)
        if normalized:
            result.append(normalized)
    return result


def _has_table_header(lines: list[str]) -> bool:
    """是否出现明确表头词。

    用「产品名称/品名/货品」而非「产品」——聊天里「产品明细」这类字眼会误触发表头判定。
    """
    return any(_TABLE_HEADER_RE.search(line) for line in lines)


_PURE_NUM_RE = re.compile(r'^\d+(?:\.\d+)?$')

# 表头单元格的字长上限（超过就不像列名了）
_MAX_LABEL_LEN = 6

# 扫描表头时的最大起始行号（真表上方可能有标题/日期）
_HEADER_SCAN_LIMIT = 12


def _is_pure_number(line: str) -> bool:
    return bool(_PURE_NUM_RE.match(line))


def _label_role(line: str) -> str | None:
    for role, keywords in _HEADER_ROLES:
        if any(kw in line for kw in keywords):
            return role
    return None


def _is_label_like(line: str) -> bool:
    """像不像一个列名：短、无数字、无冒号、含中文、且能归到某个角色"""
    if not line or len(line) > _MAX_LABEL_LEN:
        return False
    if any(ch.isdigit() for ch in line):
        return False
    if ':' in line or '：' in line:
        return False
    if _NOISE_RE.search(line) or _DATE_RE.search(line):
        return False
    return bool(re.search(r'[一-龥]', line)) and _label_role(line) is not None


def _detect_header_columns(lines: list[str]) -> tuple[list[str], int] | None:
    """识别表头块，返回 (按列顺序的角色列表, 数据起始行号)，识别不到返回 None。

    要求：连续若干「列名行」，且其中既有明确产品词、也有数量词。
    这样既避免把自由文本误当表格，也能把「单位/规格」这类不在关键词表里的列
    照样算成一列——列数错一个，整表就会错位。
    """
    start = None
    roles: list[str] = []
    for i, line in enumerate(lines[:_HEADER_SCAN_LIMIT]):
        if _is_label_like(line):
            if start is None:
                start = i
            roles.append(_label_role(line) or 'other')
            continue
        if start is not None:
            break  # 表头块结束
    if start is None:
        return None
    if 'product_name' not in roles or 'quantity' not in roles:
        return None
    if not any(label in lines[j] for j in range(start, start + len(roles))
               for label in _STRICT_PRODUCT_LABELS):
        return None
    return roles, start + len(roles)


def _is_data_cell(line: str) -> bool:
    """数据单元格候选：排除噪音、日期、合计行、列名与量词。

    量词要在「数量行之后」单独取，不能混进行首单元格里，否则会挤掉产品名。
    """
    if not line or line in UNITS:
        return False
    if _NOISE_RE.search(line) or _DATE_RE.search(line):
        return False
    if re.match(r'^(合计|总计|小计|签章|第\s*\d+\s*页|共\s*\d+\s*页)', line):
        return False
    if _is_label_like(line):
        return False
    return _is_name_like(line)


def _align_leading(
    leading: list[str],
    qty_col: int,
    product_col: int,
    customer_col: int | None,
    post_cols: int,
) -> tuple[list[str], int, int | None, bool] | None:
    """把行首单元格对齐到表头列。

    返回 (对齐后的单元格, 产品列下标, 客户列下标|None, 产品名是否要把尾列拼回)；
    无法对齐返回 None。

    关键判据是 `post_cols`＝表头里**数量列之后**还有几列。数量之后的列（备注等）
    其单元格会落进**下一行**的行首，所以：

    - 多出的格数 **≤ post_cols** → 这些是上一行漏下来的尾列，**从行首丢弃**；
    - 多出的格数 **> post_cols** → 尾列消化不完，多出的才是**产品名换行续行**（拼回）；
    - 正好等于数量列下标 → 直接按列取；
    - 少一格且客户列在首位 → 客户单元格被 OCR 漏掉，整体左移一位。
      注意此时客户留空，绝不能拿产品名顶替——那正是「把产品名当客户」的老缺陷。

    ⚠️ 「产品名换行」与「上一行尾列」在只有单元格序列时并非总能区分（两者都表现为
    多出单元格）。此处一律**优先按尾列丢弃**：被截短的产品名还能模糊匹配上，
    被污染的产品名则匹配度直接归零（实测 0.91 → 0.00）。
    """
    extras = len(leading) - qty_col
    if extras == 0:
        return leading, product_col, customer_col, False
    if extras > 0:
        keep = min(extras, post_cols)
        base = leading[keep:]
        # 尾列不足以解释多出的格数 → 剩余的是产品名换行，拼回
        return base, product_col, customer_col, extras > post_cols
    if extras == -1 and customer_col == 0:
        return leading, product_col - 1, None, False
    return None


def _parse_order_cells(lines: list[str]) -> list[dict]:
    """单元格逐行的表格：每个单元格被 OCR 输出成独立行。

    做法是**表头定列 + 数量行做锚点**：

    - 表头给出各列的角色与顺序 → 据此知道哪一列是产品、哪一列是客户；
    - 锚点落在**数量列的位置**上（行首单元格数达到数量列下标时，那个纯数字才算数量），
      而不是「本行第一个纯数字」——否则表头里数量列之前的数值列（单价/金额/序号）
      会被当成数量，整表数量全错。

    为什么不用「名称行后面跟数字行」这种更简单的配对：真实订单表有**客户名称**列，
    `网易 / 产品名 / 10000` 会被配成「网易 数量 10000」，产品名被丢掉。
    为什么不用「按表头数出的列数分组」：备注为空时 OCR 根本不输出那个单元格，
    行宽比表头少一列，按列数分组会整体错位。锚点法对空单元格天然免疫。
    """
    detected = _detect_header_columns(lines)
    if detected is None:
        return []
    roles, data_start = detected
    qty_col = roles.index('quantity')
    pre_roles = roles[:qty_col]
    if 'product_name' not in pre_roles:
        return []
    product_col = pre_roles.index('product_name')
    customer_col = pre_roles.index('customer') if 'customer' in pre_roles else None
    # 数量列之后还有几列（备注等）——这些列的单元格会漏进下一行行首，对齐时要先扣掉
    post_cols = len(roles) - qty_col - 1
    # 客户列在首位时允许它整个缺失（OCR 漏单元格）；锚点相应可以早一格
    min_leading = qty_col - (1 if customer_col == 0 else 0)

    items: list[dict] = []
    leading: list[str] = []
    i = data_start
    while i < len(lines):
        cell = lines[i]
        is_anchor = _is_pure_number(cell) and len(leading) >= min_leading
        if not is_anchor:
            # 数值列（单价/序号）也要留进 leading，否则列数对不上
            if _is_pure_number(cell) or _is_data_cell(cell):
                leading.append(cell)
            i += 1
            continue

        quantity = _parse_quantity(cell)
        i += 1
        unit = ''
        if i < len(lines) and lines[i] in UNITS:
            unit = lines[i]
            i += 1

        aligned = _align_leading(leading, qty_col, product_col, customer_col, post_cols)
        if aligned is not None and quantity > 0:
            cells, p_idx, c_idx, join_tail = aligned
            if 0 <= p_idx < len(cells):
                product = (''.join(cells[p_idx:]) if join_tail else cells[p_idx]).strip()
                customer = ''
                if c_idx is not None and 0 <= c_idx < len(cells):
                    customer = cells[c_idx].strip()
                if _is_name_like(product):
                    items.append({
                        'product_name': product,
                        'quantity': quantity,
                        'unit': unit,
                        'customer': customer,
                        'note': '',
                    })
        leading = []
    return items


# 无表头表格的锚点周期。只认「客户 / 产品 / 数量」三列，见 _parse_headerless_cells。
_HEADERLESS_PERIOD = 3


def _parse_headerless_cells(lines: list[str]) -> list[dict]:
    """无表头、单元格逐行的**三列**表（客户 / 产品 / 数量）。

    截图没截到表头时 `_parse_order_cells` 无从下手（它靠表头定列），此路径改靠
    **结构**认表。两条约束缺一不可：

    1. **锚点间隔恒为 3**。锚点＝纯数字行且其上一行是名称行；间隔按「扣掉夹在中间
       的量词行」后计算。间隔 2 是「名称 / 数字」列表（通讯录、金额清单），间隔 ≥4
       说明产品与数量之间还夹着规格等列——两者都会让产品列错位，宁可整体拒绝。
    2. **领先列（锚点往上第 2 行）在表内重复出现**。这是「客户列」的特征；各不相同
       的领先列更可能是产品/规格列，同样拒绝。

    只认这一种形态是刻意的：更宽的容错会把非表格截图**静默**解析成错行错客户的
    订单，比返回 0 条更难被发现。
    """
    anchors = [
        i for i, line in enumerate(lines)
        if i > 0 and _is_pure_number(line) and _is_data_cell(lines[i - 1])
    ]
    if len(anchors) < 2:
        return []

    for a, b in pairwise(anchors):
        units_between = sum(1 for k in range(a + 1, b) if lines[k] in UNITS)
        if (b - a) - units_between != _HEADERLESS_PERIOD:
            return []

    leads = [lines[a - 2] for a in anchors if a >= 2]
    if not leads or max(Counter(leads).values()) < 2:
        return []

    items: list[dict] = []
    for a in anchors:
        quantity = _parse_quantity(lines[a])
        if quantity <= 0:
            continue
        unit = lines[a + 1] if a + 1 < len(lines) and lines[a + 1] in UNITS else ''
        items.append({
            'product_name': lines[a - 1].strip(),
            'quantity': quantity,
            'unit': unit,
            'customer': lines[a - 2].strip() if a >= 2 else '',
            'note': '',
        })
    return items


def parse_order_document(pages: list[dict]) -> list[dict]:
    """把 OCR 文本页解析成订单条目。

    四条路径按「精度递减、容错递增」排序，命中即返回：

    1. **表头同行、列对齐的表** → 位置法解析，列对得准，最精确；
    2. **有表头、单元格逐行的表** → 表头定列 + 数量行做锚点；
    3. **无表头、单元格逐行的三列表**（客户/产品/数量）→ 靠「锚点间隔恒为 3 +
       领先列重复」认表，见 `_parse_headerless_cells`；
    4. **逐行解析** → 同一行内含名称+数量（聊天截图的主路径），对空格与对齐都不敏感。

    顺序不可随意调换：第 2、3 条都必须排在第 4 条之前。单元格表里若某产品名以数字
    结尾（如「保温杯500」），第 4 条会把行尾数字当成数量配出「保温杯/500」，
    而真实数量在下一行。

    Returns:
        每项含 product_name / quantity / unit / customer / note。
        未能识别的字段留空（customer 为空表示图上没有客户信息，由前端兜底）。
    """
    if not pages:
        return []
    all_text = '\n'.join(_normalize(p.get('text', '')) for p in pages)
    lines = [line.strip() for line in all_text.split('\n') if line.strip()]
    if not lines:
        return []

    customer = _extract_customer_from_header(lines[:10])

    items = []
    if _has_table_header(lines):
        items = _from_table_items(_parse_table_format(lines, all_text))
    if not items:
        items = _parse_order_cells(lines)
    if not items:
        items = _parse_headerless_cells(lines)
    if not items:
        items = _parse_order_lines(lines)

    if customer:
        for item in items:
            if not item['customer']:
                item['customer'] = customer
    return items
