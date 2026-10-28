"""core/response.py 单元测试（A1 成功响应构造收敛）

核心断言：`success_response(**fields)` 与既有内联写法
`{'success': True, **fields}` **逐字节等价** —— 这是本重构「前端零改动」
承诺的依据，必须由测试锁死，防止后续有人改动合并顺序造成静默的行为漂移。
"""
import pytest

pytestmark = pytest.mark.unit

from fastapi_app.core.response import success_response


class TestSuccessResponse:
    """基础构造语义"""

    def test_no_fields_returns_only_success(self):
        assert success_response() == {'success': True}

    def test_message_only(self):
        assert success_response(message='删除成功') == {
            'success': True,
            'message': '删除成功',
        }

    def test_arbitrary_fields(self):
        assert success_response(rows=[1, 2], total=2) == {
            'success': True,
            'rows': [1, 2],
            'total': 2,
        }

    def test_result_spread_pattern(self):
        """服务层最常见的用法：return success_response(**result)"""
        result = {'created_count': 3, 'orders': [{'id': 1}]}
        assert success_response(**result) == {'success': True, **result}


class TestEquivalenceWithInlineLiteral:
    """锁死与内联字面量的逐字节等价性（重构的正确性依据）"""

    @pytest.mark.parametrize(
        'fields',
        [
            {},
            {'message': '创建成功'},
            {'rows': []},
            {'order': {'id': 7}, 'message': '更新成功'},
            {'count': 0, 'items': None},
        ],
    )
    def test_equivalent_to_inline_literal(self, fields):
        assert success_response(**fields) == {'success': True, **fields}

    def test_fields_override_success_key_like_inline(self):
        """内联写法 `{'success': True, **fields}` 中 fields 可覆盖 success；
        helper 必须保持同一语义，不得擅自"修正"为强制 True。
        """
        fields = {'success': False, 'reason': 'x'}
        assert success_response(**fields) == {'success': True, **fields}
        assert success_response(**fields)['success'] is False

    def test_message_overridden_by_result_like_inline(self):
        """既有写法 `{'success': True, 'message': '创建成功', **result}` 中
        result 的 message 覆盖字面量。合并语义须在**调用侧**完成（见下条测试）。
        """
        result = {'message': '来自服务层', 'id': 9}
        assert success_response(**{'message': '创建成功', **result}) == {
            'success': True,
            'message': '来自服务层',
            'id': 9,
        }

    def test_duplicate_key_is_rejected_at_call_site(self):
        """⚠️ 回归护栏：不得写成 `success_response(message=..., **result)`。

        Python 在调用点即拒绝重复关键字 —— 若 result 含 message 键会抛
        TypeError（线上表现为 500），而原内联字面量是静默覆盖。
        本测试锁死这一约束，防止后续有人"简化"成危险写法。
        """
        result = {'message': '来自服务层'}
        with pytest.raises(TypeError, match='multiple values'):
            success_response(message='创建成功', **result)

    def test_duplicate_success_key_also_rejected(self):
        """同理，显式传 success 时不可再展开含 success 的 dict。"""
        with pytest.raises(TypeError, match='multiple values'):
            success_response(success=True, **{'success': False})


class TestIsolation:
    """每次调用返回独立字典，避免调用方互相污染"""

    def test_returns_new_dict_each_call(self):
        a = success_response()
        b = success_response()
        assert a == b
        assert a is not b

    def test_mutating_result_does_not_leak(self):
        first = success_response()
        first['injected'] = True
        assert 'injected' not in success_response()

    def test_does_not_mutate_input_mapping(self):
        payload = {'id': 1}
        success_response(**payload)
        assert payload == {'id': 1}


class TestRealWorldShapes:
    """贴合本项目实际响应形态（取自 order_routes / customer_sampling 迁移点）"""

    def test_action_response_shape(self):
        assert success_response(message='删除成功') == {
            'success': True,
            'message': '删除成功',
        }

    def test_idempotent_generate_shape(self):
        existing = [{'id': 1}, {'id': 2}]
        body = success_response(
            message=f'已存在 {len(existing)} 个对应采购单（并发幂等）',
            created_count=0,
            orders=existing,
            idempotent=True,
        )
        assert body['success'] is True
        assert body['created_count'] == 0
        assert body['idempotent'] is True
        assert body['orders'] == existing
