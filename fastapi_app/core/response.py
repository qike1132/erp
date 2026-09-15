"""统一成功响应构造工具。

**设计边界（重要，勿改成中间件）**

本项目 335 处端点通过 `response_model=` 声明响应契约（Pydantic 强类型校验 +
序列化）。因此**不引入响应包装中间件**：

1. 中间件运行在 FastAPI 完成 `response_model` 序列化**之后**，再包裹一层会产生
   `{success, data: {success, ...}}` 双重包装；
2. `response_model` 会按模型白名单过滤字段，中间件新增的键（如 `request_id`）
   在声明了 `response_model` 的端点上会被**静默丢弃**，产生"加了但看不到"的错觉。

`request_id` / `trace_id` 的正确载体是**响应头**，已由 `RequestIdMiddleware`
承担，不进入响应体。

**本模块只做「构造收敛」**：把散落在各端点的 `{'success': True, ...}` 字面量
收拢为单一函数，使响应形状有唯一来源，便于后续统一演进（调整键名、追加
分页元信息等）。

**语义等价性**：`success_response(**fields)` 与 `{'success': True, **fields}`
逐字节等价，属纯重构，前端无需任何改动。既有写法中 `**result` 恒在最后
（即 result 覆盖同名键），与本函数的合并顺序一致。

**⚠️ 调用约束（勿踩）**：不得把同一个键同时显式传入并包含在展开的 dict 里 ——

    success_response(message='创建成功', **result)      # ❌ result 含 message 时
                                                        #    TypeError（调用点即报）

Python 在**调用点**就拒绝重复关键字，任何函数签名都拦不住。需合并语义时，
必须先在调用侧合并为一个 dict 再展开（合并顺序即覆盖优先级）：

    success_response(**{'message': '创建成功', **result})   # ✅ result 覆盖字面量

这与原内联字面量 `{'success': True, 'message': '创建成功', **result}` 完全等价。
"""
from typing import Any

__all__ = ['success_response']


def success_response(**fields: Any) -> dict[str, Any]:
    """构造标准成功响应体 `{'success': True, **fields}`。

    Args:
        **fields: 附加到响应体的字段。与既有内联写法语义一致 —— 若 fields 中
            含 `success` 键，其值会覆盖默认的 True。
            注意：不要与显式关键字重复（见模块 docstring 的调用约束）。

    Returns:
        dict[str, Any]: 至少包含 `success: True` 的响应字典。

    Examples:
        >>> success_response()
        {'success': True}
        >>> success_response(message='删除成功')
        {'success': True, 'message': '删除成功'}
        >>> success_response(**{'total': 3, 'items': []})
        {'success': True, 'total': 3, 'items': []}
        >>> success_response(**{'message': '创建成功', **{'id': 9}})
        {'success': True, 'message': '创建成功', 'id': 9}
    """
    return {'success': True, **fields}
