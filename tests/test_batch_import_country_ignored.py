import pathlib


def test_parser_has_no_country_helper():
    import fastapi_app.services.batch_import_parser as parser

    assert not hasattr(parser, '_parse_country_value')


def test_import_paths_ignore_country_column():
    """带「国家」列的 Excel 行必须被正常接受（静默忽略该列）。"""
    for name in ('batch_import_service.py', 'batch_import_core.py'):
        text = pathlib.Path('fastapi_app/services', name).read_text(encoding='utf-8')
        assert "'国家'" not in text, f'{name} 仍在解析国家列'
        assert 'order_type_parsed' not in text, f'{name} 仍在推导 order_type'
