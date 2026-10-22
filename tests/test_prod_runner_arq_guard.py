"""L10：已注册外部 erp-arq 时，prod_runner 不得再启动内置 ARQ worker。"""


def test_external_arq_flag_disables_internal():
    from fastapi_app.core.prod_runner import should_start_internal_arq

    assert should_start_internal_arq([], {"ERP_ARQ_EXTERNAL": "1"}) is False
    assert should_start_internal_arq(["--no-arq"], {}) is False
    assert should_start_internal_arq([], {}) is True
