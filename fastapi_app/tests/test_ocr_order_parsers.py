"""订单 OCR 文本解析测试

纯文本入参，不依赖数据库与运行环境。

素材取自 2026-09-29 用 RapidOCR 对真实形态截图的实际输出：
- 聊天截图：空格被吞（"儿童保温杯500ml 50箱" → "儿童保温杯500ml50箱"）
- 表格截图：每个单元格被拆成独立行
"""
import pytest

from fastapi_app.services.ocr._order_parsers import UNITS, parse_order_document


def names(items):
    return [i['product_name'] for i in items]


def qtys(items):
    return [i['quantity'] for i in items]


def units(items):
    return [i['unit'] for i in items]


def pages(text: str):
    return [{'page': 0, 'text': text}]


class TestChatScreenshot:
    """聊天截图：OCR 把名称/数量/单位挤成一行"""

    CHAT = '\n'.join([
        '张老板 (华东商贸)',
        '王姐，这周要补一批货',
        '好的，明细发我',
        '儿童保温杯500ml50箱',
        '卡通雨伞8骨30把',
        '不锈钢饭盒三层20个',
        '儿童水壶600ml15箱',
        '另外加急，周五前到',
        '收到，安排',
        '09-2914:32',
    ])

    def test_names_containing_digits_not_split(self):
        """名称里的 500ml / 8骨 / 600ml 是名称的一部分，数量必须是行尾那个数"""
        items = parse_order_document(pages(self.CHAT))
        assert names(items) == [
            '儿童保温杯500ml', '卡通雨伞8骨', '不锈钢饭盒三层', '儿童水壶600ml',
        ]
        assert qtys(items) == [50, 30, 20, 15]
        assert units(items) == ['箱', '把', '个', '箱']

    def test_noise_lines_produce_no_items(self):
        """时间戳、客套话、无数量行一律不进结果"""
        items = parse_order_document(pages(self.CHAT))
        assert len(items) == 4
        joined = ' '.join(names(items))
        for noise in ['张老板', '王姐', '好的', '收到', '另外加急', '09-29']:
            assert noise not in joined

    def test_spaced_form_parses(self):
        """有的截图 OCR 会保留空格"""
        text = '儿童保温杯 500ml 50 箱\n卡通雨伞8骨  30把'
        items = parse_order_document(pages(text))
        assert qtys(items) == [50, 30]
        assert units(items) == ['箱', '把']

    def test_multi_items_split_by_separators(self):
        items = parse_order_document(pages('儿童保温杯 10箱、卡通雨伞 5把，不锈钢饭盒 3个'))
        assert len(items) == 3
        assert qtys(items) == [10, 5, 3]

    def test_item_without_unit_is_valid(self):
        items = parse_order_document(pages('卡通雨伞8骨 30'))
        assert qtys(items) == [30]
        assert units(items) == ['']

    @pytest.mark.parametrize('sep', ['x', 'X', '×', '*'])
    def test_times_sign_forms(self, sep):
        items = parse_order_document(pages(f'卡通雨伞8骨 {sep}30'))
        assert qtys(items) == [30]


class TestCustomer:
    """客户只从显式写法提取；聊天里的「张三：」不能当客户"""

    def test_explicit_customer_line(self):
        items = parse_order_document(pages('客户：华东商贸有限公司\n儿童保温杯500ml50箱'))
        assert items[0]['customer'] == '华东商贸有限公司'

    def test_chat_sender_not_customer(self):
        """「张三：产品 10箱」里的张三可能不是 ERP 里的客户，宁可留空交给前端兜底"""
        items = parse_order_document(pages('张三：儿童保温杯500ml50箱'))
        assert items[0]['customer'] == ''

    def test_company_suffix_recognized(self):
        items = parse_order_document(pages('华东商贸有限公司\n儿童保温杯500ml50箱'))
        assert items[0]['customer'] == '华东商贸有限公司'


class TestTableScreenshot:
    """表格截图：OCR 把每个单元格输出成独立行"""

    TABLE = '\n'.join([
        '客户：华东商贸有限公司',
        '订货单2026-09-29',
        '产品名称',
        '数量',
        '备注',
        '儿童保温杯500ml',
        '50',
        '箱',
        '卡通雨伞8骨',
        '30',
        '把',
        '不锈钢饭盒三层',
        '20',
        '个',
    ])

    def test_cell_per_line_table(self):
        items = parse_order_document(pages(self.TABLE))
        assert names(items) == ['儿童保温杯500ml', '卡通雨伞8骨', '不锈钢饭盒三层']
        assert qtys(items) == [50, 30, 20]
        assert items[0]['customer'] == '华东商贸有限公司'

    def test_third_column_unit_maps_to_unit(self):
        """表头有「备注」列但内容其实是单位，要归到 unit；本轮不提取备注"""
        items = parse_order_document(pages(self.TABLE))
        assert units(items) == ['箱', '把', '个']
        assert all(i['note'] == '' for i in items)

    def test_table_with_unit_column_not_misaligned(self):
        """回归：表头是「产品名称/数量/单位」时，按关键词只能数出 2 列，
        曾导致整表错位、产出「名称=单位 数量=500」的垃圾条目。

        这一条是端到端跑真实 OCR 时才暴露的——单测 fixture 用「备注」恰好
        在关键词表内，掩盖了问题。"""
        text = '\n'.join([
            '客户：华东商贸有限公司',
            '订货单2026-09-29',
            '产品名称', '数量', '单位',
            '儿童保温杯500ml', '50', '箱',
            '卡通雨伞8骨', '30', '把',
            '不锈钢饭盒三层', '20', '个',
            '儿童水壶600ml', '15', '箱',
        ])
        items = parse_order_document(pages(text))
        assert names(items) == ['儿童保温杯500ml', '卡通雨伞8骨', '不锈钢饭盒三层', '儿童水壶600ml']
        assert qtys(items) == [50, 30, 20, 15]
        assert units(items) == ['箱', '把', '个', '箱']
        assert items[0]['customer'] == '华东商贸有限公司'

    def test_unknown_columns_do_not_break_pairing(self):
        """规格/单价/金额等列名不在任何关键词表里，同样不能影响配对"""
        text = '\n'.join([
            '产品名称', '规格', '数量', '单价', '金额',
            '儿童保温杯500ml', '500ml', '50', '12.5', '625',
            '卡通雨伞8骨', '8骨', '30', '9', '270',
        ])
        items = parse_order_document(pages(text))
        assert names(items) == ['儿童保温杯500ml', '卡通雨伞8骨']
        assert qtys(items) == [50, 30]

    def test_aligned_same_line_table(self):
        """同一行分列的表：列必须对齐（位置法解析依赖对齐），此处用 ljust 精确构造"""
        text = '\n'.join([
            '产品名称'.ljust(14) + '数量',
            '儿童保温杯500ml'.ljust(14) + '50',
            '卡通雨伞8骨'.ljust(14) + '30',
        ])
        items = parse_order_document(pages(text))
        assert names(items) == ['儿童保温杯500ml', '卡通雨伞8骨']
        assert qtys(items) == [50, 30]

    def test_unaligned_same_line_table_no_garbage(self):
        """列没对齐时宁可走逐行解析，也不能把整行当成一个产品名"""
        text = '产品名称          数量\n儿童保温杯500ml   50\n卡通雨伞8骨       30'
        items = parse_order_document(pages(text))
        assert names(items) == ['儿童保温杯500ml', '卡通雨伞8骨']
        assert qtys(items) == [50, 30]


class TestRealOrderTable:
    """用户真机实测的表（2026-09-29）——客户名称列 + 空的备注列

    真实缺陷：单元格解析原本是「名称行后面跟数字行就配对」，遇到
    `网易 / 产品名 / 10000` 会把**客户当成产品名**，产品名被丢掉。
    且备注为空时 OCR 不输出空单元格，行宽比表头少一列。
    """

    # 实际截图里的内容（表头 4 列，备注空）
    REAL = '\n'.join([
        '客户名称', '产品名称', '订单数量', '备注',
        '网易', '《蛋仔派对》团子木鱼毛绒挂件盲盒', '10000',
        '网易', '《蛋仔派对》市集拾趣系列 毛绒公仔挂件盲盒', '10000',
    ])

    def test_customer_column_not_taken_as_product(self):
        items = parse_order_document(pages(self.REAL))
        assert names(items) == [
            '《蛋仔派对》团子木鱼毛绒挂件盲盒',
            '《蛋仔派对》市集拾趣系列 毛绒公仔挂件盲盒',
        ]
        assert qtys(items) == [10000, 10000]

    def test_customer_column_value_maps_to_customer(self):
        items = parse_order_document(pages(self.REAL))
        assert [i['customer'] for i in items] == ['网易', '网易']

    def test_empty_note_column_keeps_rows_aligned(self):
        """备注列为空时 OCR 不输出该单元格，行宽少一列，仍要能对齐"""
        items = parse_order_document(pages(self.REAL))
        assert len(items) == 2
        assert all(i['note'] == '' for i in items)

    def test_wrapped_product_name_is_rejoined(self):
        """长产品名在截图中换行，OCR 会拆成两行"""
        text = '\n'.join([
            '客户名称', '产品名称', '订单数量',
            '网易', '《蛋仔派对》市集拾趣系列', '毛绒公仔挂件盲盒', '10000',
        ])
        items = parse_order_document(pages(text))
        assert qtys(items) == [10000]
        assert items[0]['customer'] == '网易'
        assert '毛绒公仔挂件盲盒' in items[0]['product_name']

    def test_real_table_with_unit_column(self):
        text = '\n'.join([
            '客户名称', '产品名称', '订单数量', '单位',
            '网易', '团子木鱼毛绒挂件盲盒', '10000', '箱',
        ])
        items = parse_order_document(pages(text))
        assert qtys(items) == [10000]
        assert units(items) == ['箱']
        assert items[0]['customer'] == '网易'

    def test_numeric_customer_name_not_taken_as_product(self):
        """客户名是纯数字时也不能被当成产品名"""
        text = '\n'.join([
            '客户名称', '产品名称', '订单数量',
            '001', '团子木鱼毛绒挂件盲盒', '10000',
        ])
        items = parse_order_document(pages(text))
        assert names(items) == ['团子木鱼毛绒挂件盲盒']


class TestReviewRegressions:
    """2026-09-29 代码审核查出的缺陷，逐条钉住"""

    def test_decimal_spec_does_not_drop_the_line(self):
        """小数规格（2.5L / 1.8m）曾被日期正则误判，整行被丢弃"""
        items = parse_order_document(pages('凉席1.8m 20条\n保温杯2.5L 10个'))
        assert names(items) == ['凉席1.8m', '保温杯2.5L']
        assert qtys(items) == [20, 10]

    def test_decimal_quantity_still_parsed(self):
        items = parse_order_document(pages('保温杯 1.5个'))
        assert len(items) == 1
        assert items[0]['unit'] == '个'

    def test_real_date_lines_still_skipped(self):
        """日期护栏本身不能被削弱"""
        items = parse_order_document(pages('订货单2026-09-29\n客户：华东商贸\n保温杯500ml 10箱'))
        assert qtys(items) == [10]
        assert items[0]['customer'] == '华东商贸'

    def test_note_cell_does_not_corrupt_next_row(self):
        """备注列有内容时，曾被拼到下一行的产品名上（加急雨伞）"""
        text = '\n'.join([
            '产品名称', '数量', '备注',
            '保温杯', '100', '加急',
            '雨伞', '50',
        ])
        items = parse_order_document(pages(text))
        assert names(items) == ['保温杯', '雨伞']
        assert qtys(items) == [100, 50]

    def test_missing_customer_cell_is_not_filled_by_product(self):
        """客户单元格被 OCR 漏掉时，曾把产品名当成客户"""
        text = '\n'.join(['客户名称', '产品名称', '数量', '保温杯', '100'])
        items = parse_order_document(pages(text))
        assert items[0]['customer'] == ''
        assert items[0]['product_name'] == '保温杯'

    def test_price_column_before_quantity_does_not_become_quantity(self):
        """数量列之前的数值列（单价）曾被当成数量"""
        text = '\n'.join([
            '产品名称', '单价', '数量',
            '保温杯', '25', '100',
            '雨伞', '18', '50',
        ])
        items = parse_order_document(pages(text))
        assert qtys(items) == [100, 50]

    def test_spaced_name_ending_with_digit_is_kept(self):
        """`文件夹A4 100个` 曾整行被丢（名称以数字结尾）"""
        items = parse_order_document(pages('文件夹A4 100个'))
        assert names(items) == ['文件夹A4']
        assert qtys(items) == [100]
        assert units(items) == ['个']

    def test_space_preserved_form_is_preferred(self):
        items = parse_order_document(pages('文件夹A4 100个\n单据本B5 200本'))
        assert names(items) == ['文件夹A4', '单据本B5']
        assert qtys(items) == [100, 200]

    def test_model_suffix_x_is_not_eaten_as_multiplier(self):
        """`iPhone X 100台` 的型号尾巴 X 曾被当成乘号"""
        items = parse_order_document(pages('iPhone X 100台'))
        assert names(items) == ['iPhone X']
        assert qtys(items) == [100]

    def test_multiplier_still_recognised(self):
        """乘号本身仍要认（紧跟数字）"""
        for text in ['卡通雨伞8骨 x30', '卡通雨伞8骨 ×30', '卡通雨伞8骨 *30']:
            items = parse_order_document(pages(text))
            assert qtys(items) == [30], text

    def test_tight_form_digit_boundary_is_greedy_by_design(self):
        """无空格时「名称尾部数字」与「数量」本质歧义，取贪婪读法（已文档化）"""
        items = parse_order_document(pages('文件夹A4100个'))
        assert items[0]['quantity'] == 4100


class TestQuantityColumnTrailingColumns:
    """数量之后的列（备注等）其单元格会漏进下一行行首。

    真实缺陷（2026-09-29 用户实测）：有**客户列**时，这些漏下来的单元格被当成
    「产品名换行续行」拼回产品名，于是「备注变客户、客户名并进产品名」。
    产品名一旦被污染，模糊匹配从 0.91 掉到 0.00 —— 用户看到的就是「加几个字就识别不出来」。
    """

    def test_note_does_not_become_next_customer(self):
        text = '\n'.join([
            '客户名称', '产品名称', '订单数量', '备注',
            '网易', '团子木鱼毛绒挂件盲盒', '10000', '加急',
            '网易', '咸鱼按摩捶', '242',
        ])
        items = parse_order_document(pages(text))
        assert [i['customer'] for i in items] == ['网易', '网易']
        assert names(items) == ['团子木鱼毛绒挂件盲盒', '咸鱼按摩捶']
        assert qtys(items) == [10000, 242]

    def test_note_does_not_pollute_product_name(self):
        text = '\n'.join([
            '客户名称', '产品名称', '订单数量', '备注',
            '网易', '团子木鱼毛绒挂件盲盒', '10000', '发货期',
            '网易', '咸鱼按摩捶', '242', '加急',
        ])
        items = parse_order_document(pages(text))
        assert names(items) == ['团子木鱼毛绒挂件盲盒', '咸鱼按摩捶']

    def test_all_rows_without_note_still_aligned(self):
        """对照组：备注为空时行为不变"""
        text = '\n'.join([
            '客户名称', '产品名称', '订单数量', '备注',
            '网易', '团子木鱼毛绒挂件盲盒', '10000',
            '网易', '咸鱼按摩捶', '242',
        ])
        items = parse_order_document(pages(text))
        assert names(items) == ['团子木鱼毛绒挂件盲盒', '咸鱼按摩捶']
        assert qtys(items) == [10000, 242]

    def test_extra_columns_between_product_and_quantity(self):
        """产品与数量之间还有别的列时，那些单元格不能被并进产品名"""
        text = '\n'.join([
            '客户名称', '产品名称', '规格', '订单数量',
            '网易', '咸鱼按摩捶', '大号', '242',
        ])
        items = parse_order_document(pages(text))
        assert names(items) == ['咸鱼按摩捶']
        assert qtys(items) == [242]
        assert items[0]['customer'] == '网易'

    def test_user_real_table_parses_all_four_rows(self):
        """用户实测表（客户名称|产品名称|订单数量|备注，备注空）四行都要读对。

        产品名里本来就有多余文字（菲菲…发潜伏期 / 试试 / 11菲菲），
        那是名称单元格的内容，解析侧必须原样保留交给匹配侧处理，不能改动。
        """
        text = '\n'.join([
            '客户名称', '产品名称', '订单数量', '备注',
            '网易', '菲菲 团子木鱼毛绒挂件盲盒  发潜伏期', '10000',
            '网易', '市集拾趣系列  试试毛绒公仔挂件盲盒', '2424',
            'MINISO国内', '鲨的鱼', '242',
            'TOP TOY', '咸鱼按摩捶 11菲菲', '11',
        ])
        items = parse_order_document(pages(text))
        assert [i['customer'] for i in items] == ['网易', '网易', 'MINISO国内', 'TOP TOY']
        assert qtys(items) == [10000, 2424, 242, 11]
        assert names(items) == [
            '菲菲 团子木鱼毛绒挂件盲盒  发潜伏期',
            '市集拾趣系列  试试毛绒公仔挂件盲盒',
            '鲨的鱼',
            '咸鱼按摩捶 11菲菲',
        ]


class TestGuards:
    """不该产出条目的输入"""

    def test_empty_input(self):
        assert parse_order_document([]) == []
        assert parse_order_document(pages('')) == []

    def test_text_without_quantity(self):
        items = parse_order_document(pages('王姐，这周要补一批货\n好的，明细发我\n收到，安排'))
        assert items == []

    def test_zero_or_negative_quantity(self):
        items = parse_order_document(pages('卡通雨伞8骨 0箱\n不锈钢饭盒 0个'))
        assert items == []

    def test_too_short_name(self):
        """单个字符的行多是表头或噪音，不是产品名"""
        items = parse_order_document(pages('箱 10\n个 20'))
        assert items == []

    def test_malformed_quantity(self):
        items = parse_order_document(pages('卡通雨伞8骨 1.5.5箱'))
        assert items == []


class TestHeaderlessTable:
    """无表头三列表（客户 / 产品 / 数量），OCR 每格独立成行。

    素材取自 2026-10-15 用户真机截图（无表头，首行即数据）经 RapidOCR 的实际输出。
    没有表头可依，只能靠**结构**认表：锚点间隔恒为 3 + 领先列重复（见
    `_parse_headerless_cells`）。本类同时钉住「不认什么」——收紧的边界与认表同等重要。
    """

    REAL = '\n'.join([
        'MINISO国际',
        '3寸MINIFAMILY蒸包毛绒挂件（GIGI猪）',
        '1680',
        'MINISO国际',
        '3寸MINIFAMILY蒸包毛绒挂件（墩墩）',
        '3360',
        'MINISO国际',
        'MINIFAMILY杯面团子系列毛绒公仔盲盒',
        '8512',
    ])

    def test_three_column_headerless_table_parses(self):
        items = parse_order_document(pages(self.REAL))
        assert names(items) == [
            '3寸MINIFAMILY蒸包毛绒挂件（GIGI猪）',
            '3寸MINIFAMILY蒸包毛绒挂件（墩墩）',
            'MINIFAMILY杯面团子系列毛绒公仔盲盒',
        ]
        assert qtys(items) == [1680, 3360, 8512]

    def test_repeated_leading_column_maps_to_customer(self):
        items = parse_order_document(pages(self.REAL))
        assert [i['customer'] for i in items] == ['MINISO国际', 'MINISO国际', 'MINISO国际']

    def test_spec_column_makes_period_four_and_is_rejected(self):
        """客户/产品/规格/数量（锚点间隔 4）→ 拒绝。

        相邻配对会取到「规格」当产品名（间隔 4 时产品列不在锚点上一行），
        整表产品全错、模糊匹配归零——比返回 0 条更糟，故整体拒绝。

        产品名刻意不以数字结尾：否则逐行解析（路径 3 的贪婪紧凑正则）会
        先把它拆成「名称 / 尾数」，掩盖兜底路径本身的行为。
        """
        text = '\n'.join([
            'MINISO国际', '蒸包挂件', '大号', '1680',
            'MINISO国际', '毛绒公仔', '大号', '3360',
        ])
        assert parse_order_document(pages(text)) == []

    def test_serial_number_column_makes_period_four_and_is_rejected(self):
        """序号/客户/产品/数量（锚点间隔 4）→ 拒绝。

        此形态与「客户/产品/规格/数量」在结构上无法区分（两者都让锚点上一行不再是
        产品），保守起见整体拒绝。该用例专门钉住「锚点间隔必须等于 3」这条约束——
        它的领先列是重复的（客户），仅靠「领先列重复」一条挡不住。
        """
        text = '\n'.join([
            '1', 'MINISO国际', '蒸包挂件', '1680',
            '2', 'MINISO国际', '毛绒公仔', '3360',
        ])
        assert parse_order_document(pages(text)) == []

    def test_chat_number_lines_are_rejected(self):
        """「名称 / 数字」列表（锚点间隔 2）与订单表结构上不可分，宁可拒绝。

        否则「张三 / 13800138000」这类通讯录/金额行会被当成订单（电话号当数量）。
        """
        text = '\n'.join([
            '张三', '13800138000', '李四', '13900139000', '王五', '13700137000',
        ])
        assert parse_order_document(pages(text)) == []

    def test_two_column_table_is_out_of_scope(self):
        """产品/数量两列（间隔 2）不在本次收紧范围内，同样拒绝"""
        text = '\n'.join(['儿童保温杯', '50', '卡通雨伞', '30', '水壶', '20'])
        assert parse_order_document(pages(text)) == []

    def test_non_repeating_leading_column_is_rejected(self):
        """领先列各不相同 → 不是客户列（可能是产品/规格列），拒绝"""
        text = '\n'.join([
            '张三', '保温杯', '100',
            '李四', '雨伞', '200',
            '王五', '水壶', '300',
        ])
        assert parse_order_document(pages(text)) == []

    def test_unit_lines_do_not_break_period(self):
        """锚点之间夹着量词行时，扣掉量词后周期仍是 3"""
        text = '\n'.join([
            'MINISO国际', '儿童保温杯', '50', '箱',
            'MINISO国际', '卡通雨伞', '30', '箱',
        ])
        items = parse_order_document(pages(text))
        assert names(items) == ['儿童保温杯', '卡通雨伞']
        assert qtys(items) == [50, 30]
        assert units(items) == ['箱', '箱']

    def test_single_row_is_rejected(self):
        """只有一组「名称 / 数量」不足以判定是表格"""
        assert parse_order_document(pages('MINISO国际\n儿童保温杯\n50')) == []


class TestUnits:
    def test_units_cover_common_measure_words(self):
        for u in ['箱', '件', '个', '包', '袋', '盒', '条', '只', '支', '瓶', '桶', '套', '把']:
            assert u in UNITS

    def test_spec_suffixes_are_not_units(self):
        """ml / g 是产品规格，不能当量词，否则「儿童保温杯500ml」会被拆错"""
        assert 'ml' not in UNITS
        assert 'g' not in UNITS
