import ast

try:
    with open('app.py', encoding='utf-8') as f:
        content = f.read()
    # 检查语法
    ast.parse(content)
    print('App.py syntax is correct!')
except SyntaxError as e:
    print(f'Syntax error in app.py: {e}')
    print(f'Line {e.lineno}, column {e.col_offset}')
except Exception as e:
    print(f'Error in app.py: {e}')
    import traceback
    traceback.print_exc()
