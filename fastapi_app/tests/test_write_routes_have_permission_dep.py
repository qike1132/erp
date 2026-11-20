"""结构层：每个写路由都必须有权限码依赖，或登记了可判定的替代授权机制（审计 3.1）。

反射整棵路由树 → 「没挂权限码的写路由」必须**恰好等于**豁免表里的条目；豁免表里的条目
反过来也必须仍然是「没挂权限码的写路由」（僵尸条目要删掉）。

2026-11-19 推送前评审修了两个真缺口（都是「守卫看着在、其实不拦」）：

1. **键不能用裸 `route.path`**。被 `include_router` 挂载后 `route.path` 不含 include 前缀，
   当时 4 个 `/upload`（auth / ocr-import / purchase-plan / production-plan）塌成同一个键
   `('POST', '/upload')` —— 豁免表里一行替四条挡枪，其中一个被降级成「登录即可」也照样绿。
   现在键是**含前缀的完整模板路径**，并加了一条「无码行数 == 无码键数」的恒等断言：
   将来再出现塌键，当场红而不是静默合并。
2. **豁免理由不可判定**。原来『生产记录：resolve_production_write_scope 范围校验』只是一句
   字符串，把那个依赖删掉理由仍然成立。现在 `REQUIRED_AUTH_MECHANISM` 把「哪些豁免必须能在
   依赖树上找到哪个函数」写成断言。

反射实现（展开 `_IncludedRouter`、累积前缀、递归收权限码/函数名）在
`fastapi_app/tests/_route_introspect.py`，行为层 `tests/test_write_endpoint_permission_denied.py`
共用同一份 —— 两份实现必然漂移。
"""
from __future__ import annotations

from fastapi_app.main import app
from fastapi_app.tests._route_introspect import write_routes

#: 没有权限码、但确实有其它授权机制的写路由。键 = (method, **含 include 前缀**的完整模板路径)。
#: 每条都必须写清「靠什么授权」——没有理由的豁免等于把守卫关掉。
ALLOWED_WITHOUT_PERMISSION_CODE: dict[tuple[str, str], str] = {
    ('POST', '/api/v1/daily-production/records'):
        '生产记录新增：resolve_production_write_scope 范围校验（部门/产品）+ get_current_user_with_permissions',
    ('PUT', '/api/v1/daily-production/records/{record_id}'):
        '生产记录编辑：同上（范围在端点内校验）',
    ('DELETE', '/api/v1/daily-production/records/{record_id}'):
        '生产记录删除：同上',
    ('POST', '/api/v1/notifications/{notification_id}/read'):
        '通知已读：get_current_user_id，作用域天然是本人',
    ('POST', '/api/v1/notifications/read-all'):
        '通知全部已读：同上',
    ('POST', '/api/v1/auth/login'):
        '认证入口：不可能要求权限码',
    ('POST', '/api/v1/auth/logout'):
        '认证出口：只需要 bearer',
    ('POST', '/api/v1/auth/refresh'):
        '令牌刷新：只需要 refresh_token',
    ('POST', '/api/v1/auth/upload'):
        '通用文件上传：get_current_user_id_write_strict（资源级校验在调用方端点）',
    ('POST', '/api/v1/auth/logs/frontend-error'):
        '前端错误上报：get_current_user_id_write_strict（已登录即可）',
    ('POST', '/api/v1/monitoring/vitals'):
        '前端性能指标上报：已登录即可，不涉业务数据',
}

#: 豁免理由必须可判定：键 → 依赖树上必须能找到的函数名。不在表里的键说明理由仍是「纯文字」。
REQUIRED_AUTH_MECHANISM: dict[tuple[str, str], str] = {
    ('POST', '/api/v1/daily-production/records'): 'resolve_production_write_scope',
    ('PUT', '/api/v1/daily-production/records/{record_id}'): 'resolve_production_write_scope',
    ('DELETE', '/api/v1/daily-production/records/{record_id}'): 'resolve_production_write_scope',
}

#: 带权限码的写路由数量下限（2026-11-19 删除 4 个死端点后实测 188，全量写路由 199）。
#: 只允许上升：低于它说明「反射不到依赖」或「大量路由被摘掉了权限码」，两种都必须当场看见。
MIN_WRITE_ROUTES_WITH_CODES = 188


def test_every_write_route_has_an_authorization_mechanism():
    rows = write_routes(app)

    without_codes_rows = [(row.method, row.path) for row in rows if not row.codes]
    without_codes = set(without_codes_rows)

    # 塌键守卫：一行豁免替多条路由挡枪时，「无码行数」会大于「无码键数」。
    assert len(without_codes_rows) == len(without_codes), (
        '有多个写路由塌到了同一个键上（很可能又是 include 前缀没带）：'
        f'行数 {len(without_codes_rows)} ≠ 键数 {len(without_codes)}；'
        f'实际键：{sorted(without_codes)}'
    )

    unexpected = sorted(without_codes - set(ALLOWED_WITHOUT_PERMISSION_CODE))
    assert unexpected == [], (
        '这些写端点既没有权限码依赖、也没有在 ALLOWED_WITHOUT_PERMISSION_CODE 里登记理由：'
        f'{unexpected} —— 很可能是漏挂 Depends(require_permission(...))'
    )

    stale = sorted(set(ALLOWED_WITHOUT_PERMISSION_CODE) - without_codes)
    assert stale == [], (
        f'豁免表里有已失效条目（这些路由现在有权限码或已不存在）：{stale} —— 请删掉，'
        '否则豁免表会越攒越大，最后没人敢动'
    )


def test_exemptions_that_claim_a_mechanism_actually_have_it():
    """豁免理由不能只是文字：声称靠某个依赖授权，就必须能在依赖树上找到它。"""
    by_key = {(row.method, row.path): row for row in write_routes(app)}

    missing: list[str] = []
    for key, func_name in REQUIRED_AUTH_MECHANISM.items():
        row = by_key.get(key)
        if row is None:
            missing.append(f'{key} 路由已不存在（请同步删掉 REQUIRED_AUTH_MECHANISM 条目）')
            continue
        if func_name not in row.call_names:
            missing.append(
                f'{key} 的依赖树上找不到 {func_name}（现有依赖：{sorted(row.call_names)}）'
            )
    assert missing == [], (
        '这些豁免的「另一种授权机制」已经不在了，豁免理由失效：' + '；'.join(missing)
    )

    # 反向：声称有替代机制的豁免，必须是豁免表里的条目；否则表与断言各说一套。
    orphan = sorted(set(REQUIRED_AUTH_MECHANISM) - set(ALLOWED_WITHOUT_PERMISSION_CODE))
    assert orphan == [], f'REQUIRED_AUTH_MECHANISM 里的键不在豁免表中：{orphan}'


def test_write_route_coverage_floor():
    """扫描面下限：反射不到依赖、或大量路由被摘掉权限码时，上面的断言会「空集也通过」。"""
    rows = write_routes(app)
    with_codes = [row for row in rows if row.codes]
    assert len(with_codes) >= MIN_WRITE_ROUTES_WITH_CODES, (
        f'带权限码的写路由只剩 {len(with_codes)} 条（下限 {MIN_WRITE_ROUTES_WITH_CODES}）：'
        '要么 _IncludedRouter 展开失效（反射不到依赖），要么权限码被批量摘掉'
    )
