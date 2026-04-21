"""
新依赖库集成测试

测试内容:
- chardet: 编码检测
- pypinyin: 拼音转换
- arrow: 日期处理
- bleach: XSS防护
- rapidfuzz: 模糊搜索（替代 fuzzywuzzy）
- XlsxWriter: Excel生成

注意: phonenumbers不在本次升级范围内，不做任何修改
"""

import pytest
import chardet
from pypinyin import lazy_pinyin, pinyin, Style
import arrow
from datetime import datetime, timedelta
import bleach
from rapidfuzz import fuzz, process


class TestChardet:
    """chardet库测试"""
    
    def test_detect_utf8(self):
        """测试UTF-8编码检测"""
        data = "中文测试内容".encode('utf-8')
        result = chardet.detect(data)
        assert result['encoding'].lower() in ['utf-8', 'ascii']
        assert result['confidence'] > 0.5
    
    def test_detect_gbk(self):
        """测试GBK编码检测"""
        data = "中文测试内容".encode('gbk')
        result = chardet.detect(data)
        assert result['encoding'] is not None
    
    def test_detect_ascii(self):
        """测试ASCII编码检测"""
        data = b"Hello World"
        result = chardet.detect(data)
        assert result['encoding'].lower() in ['ascii', 'utf-8']
    
    def test_empty_data(self):
        """测试空数据"""
        result = chardet.detect(b"")
        assert result is not None
    
    def test_mixed_content(self):
        """测试混合内容"""
        data = "Hello 你好 World 世界".encode('utf-8')
        result = chardet.detect(data)
        assert result['encoding'].lower() in ['utf-8', 'ascii']


class TestPypinyin:
    """pypinyin库测试"""
    
    def test_basic_pinyin(self):
        """测试基础拼音转换"""
        result = lazy_pinyin("苹果手机")
        assert result == ['ping', 'guo', 'shou', 'ji']
    
    def test_pinyin_abbr(self):
        """测试首字母提取"""
        result = ''.join([x[0] for x in lazy_pinyin("苹果手机")])
        assert result == "pgsj"
    
    def test_pinyin_with_tone(self):
        """测试带声调拼音"""
        result = pinyin("中国", style=Style.TONE)
        assert result == [['zhōng'], ['guó']]
    
    def test_mixed_content(self):
        """测试中英文混合"""
        result = lazy_pinyin("iPhone手机")
        assert 'iPhone' in result or 'iphone' in ''.join(result).lower()
    
    def test_numbers(self):
        """测试数字"""
        result = lazy_pinyin("123")
        assert result == ['123']
    
    def test_empty_string(self):
        """测试空字符串"""
        result = lazy_pinyin("")
        assert result == []
    
    def test_special_chars(self):
        """测试特殊字符"""
        result = lazy_pinyin("!@#$%")
        assert result == ['!@#$%']


class TestArrow:
    """arrow库测试"""
    
    def test_parse_standard_date(self):
        """测试标准日期解析"""
        dt = arrow.get("2024-01-15")
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15
    
    def test_parse_slash_date(self):
        """测试斜杠日期解析"""
        dt = arrow.get("2024/01/15", "YYYY/MM/DD")
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15
    
    def test_now(self):
        """测试当前时间"""
        now = arrow.now()
        assert now.year == datetime.now().year
    
    def test_shift_days(self):
        """测试日期偏移"""
        now = arrow.now()
        tomorrow = now.shift(days=1)
        assert tomorrow.day != now.day or tomorrow.month != now.month
    
    def test_floor_day(self):
        """测试日期取整到天"""
        dt = arrow.get("2024-01-15 15:30:45")
        floor = dt.floor('day')
        assert floor.hour == 0
        assert floor.minute == 0
        assert floor.second == 0
    
    def test_ceil_day(self):
        """测试日期取整到天末"""
        dt = arrow.get("2024-01-15 15:30:45")
        ceil = dt.ceil('day')
        assert ceil.hour == 23
        assert ceil.minute == 59
        assert ceil.second == 59
    
    def test_floor_month(self):
        """测试月初"""
        dt = arrow.get("2024-01-15")
        floor = dt.floor('month')
        assert floor.day == 1
    
    def test_ceil_month(self):
        """测试月末"""
        dt = arrow.get("2024-01-15")
        ceil = dt.ceil('month')
        assert ceil.day == 31
    
    def test_floor_week(self):
        """测试周一"""
        dt = arrow.get("2024-01-15")
        floor = dt.floor('week')
        assert floor.isoweekday() == 1
    
    def test_ceil_week(self):
        """测试周日"""
        dt = arrow.get("2024-01-15")
        ceil = dt.ceil('week')
        assert ceil.isoweekday() == 7
    
    def test_humanize(self):
        """测试人性化显示"""
        now = arrow.now()
        past = now.shift(hours=-2)
        result = past.humanize(now)
        assert "ago" in result.lower() or "前" in result


class TestBleach:
    """bleach库测试"""
    
    def test_sanitize_script_tag(self):
        """测试过滤script标签"""
        html = "<script>alert('xss')</script>"
        result = bleach.clean(html, tags=[], strip=True)
        assert "<script>" not in result
    
    def test_sanitize_safe_tags(self):
        """测试保留安全标签"""
        html = "<b>粗体</b><i>斜体</i>"
        result = bleach.clean(html, tags=['b', 'i'], strip=True)
        assert "<b>" in result
        assert "<i>" in result
    
    def test_sanitize_dangerous_attributes(self):
        """测试过滤危险属性"""
        html = '<a onclick="alert(1)" href="http://example.com">链接</a>'
        result = bleach.clean(html, tags=['a'], attributes={'a': ['href']}, strip=True)
        assert "onclick" not in result
        assert "href" in result
    
    def test_sanitize_empty(self):
        """测试空值"""
        result = bleach.clean("", tags=[], strip=True)
        assert result == ""
    
    def test_sanitize_plain_text(self):
        """测试纯文本"""
        text = "这是普通文本"
        result = bleach.clean(text, tags=[], strip=True)
        assert result == text
    
    def test_sanitize_nested_tags(self):
        """测试嵌套标签"""
        html = "<div><script>alert(1)</script><p>安全内容</p></div>"
        result = bleach.clean(html, tags=['p'], strip=True)
        assert "<script>" not in result
        assert "<p>" in result


class TestRapidfuzz:
    """rapidfuzz库测试（替代 fuzzywuzzy）"""
    
    def test_exact_match(self):
        """测试精确匹配"""
        score = fuzz.ratio("苹果手机", "苹果手机")
        assert score == 100
    
    def test_partial_match(self):
        """测试部分匹配"""
        score = fuzz.ratio("苹果手机", "苹果")
        assert 50 < score < 100
    
    def test_no_match(self):
        """测试无匹配"""
        score = fuzz.ratio("苹果手机", "香蕉")
        assert score < 50
    
    def test_fuzzy_search(self):
        """测试模糊搜索"""
        choices = {
            1: "苹果手机",
            2: "华为手机",
            3: "小米手机",
            4: "三星手机"
        }
        results = process.extract("苹果", choices, limit=2)
        assert results[0][0] == "苹果手机"
    
    def test_threshold_filter(self):
        """测试阈值过滤"""
        choices = {1: "苹果手机", 2: "香蕉"}
        results = process.extract("苹果", choices)
        filtered = [r for r in results if r[1] >= 70]
        assert len(filtered) == 1
        assert filtered[0][0] == "苹果手机"
    
    def test_wratio(self):
        """测试加权比率"""
        score = fuzz.WRatio("apple phone", "apple iPhone phone")
        assert score > 60
    
    def test_token_sort(self):
        """测试词序排序匹配"""
        score = fuzz.token_sort_ratio("apple phone", "phone apple")
        assert score >= 90


class TestIntegration:
    """集成测试"""

    def test_phone_validation_with_chinese(self):
        """测试中文手机号验证 - 使用现有正则验证"""
        phone_str = "我的手机号是13812345678"
        import re
        match = re.search(r'1[3-9]\d{9}', phone_str)
        assert match is not None
        assert len(match.group()) == 11
    
    def test_pinyin_search_integration(self):
        """测试拼音搜索集成"""
        products = [
            {"id": 1, "name": "苹果手机"},
            {"id": 2, "name": "华为手机"},
            {"id": 3, "name": "小米手机"}
        ]
        
        query = "pingguo"
        query_pinyin = query
        
        for product in products:
            product_pinyin = ''.join(lazy_pinyin(product["name"]))
            if query_pinyin in product_pinyin:
                assert product["id"] == 1
                break
    
    def test_date_range_calculation(self):
        """测试日期范围计算"""
        now = arrow.now()
        start, end = now.floor('month'), now.ceil('month')
        
        assert start.day == 1
        assert end.day >= 28
    
    def test_xss_protection_integration(self):
        """测试XSS防护集成"""
        user_input = '<script>alert("xss")</script>这是备注'
        clean_input = bleach.clean(user_input, tags=[], strip=True)
        
        assert "<script>" not in clean_input
        assert "这是备注" in clean_input


class TestPerformance:
    """性能测试"""
    
    def test_chardet_performance(self):
        """测试chardet性能"""
        import time
        data = "测试内容" * 1000
        encoded = data.encode('utf-8')

        start = time.time()
        for _ in range(10):
            chardet.detect(encoded[:10000])
        elapsed = time.time() - start

        assert elapsed < 5.0
    
    def test_pinyin_performance(self):
        """测试拼音转换性能"""
        import time
        text = "苹果手机" * 100
        
        start = time.time()
        for _ in range(100):
            lazy_pinyin(text)
        elapsed = time.time() - start
        
        assert elapsed < 2.0
    
    def test_arrow_performance(self):
        """测试arrow性能"""
        import time
        
        start = time.time()
        for _ in range(1000):
            arrow.now()
        elapsed = time.time() - start
        
        assert elapsed < 1.0


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
