"""F3-1：file_size_gate 必须扫描「改名+扩容」的文件，纯改名豁免。"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / 'scripts' / 'file_size_gate.py'


def test_rename_plus_growth_is_caught(tmp_path):
    """真实 git 仓库：git mv + 追加超限内容，门禁必须失败（旧 AM 过滤会漏）。"""
    def git(*args):
        subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True)

    git('init', '-q')
    git('config', 'user.email', 'test@example.com')
    git('config', 'user.name', 'test')
    (tmp_path / 'a.py').write_text('x = 1\n', encoding='utf-8')
    git('add', 'a.py')
    git('commit', '-qm', 'init')

    git('mv', 'a.py', 'b.py')
    (tmp_path / 'b.py').write_text('x = 1\n' + 'y = 2\n' * 20, encoding='utf-8')
    git('add', '-A')
    git('commit', '-qm', 'rename and grow')

    result = subprocess.run(
        [sys.executable, str(SCRIPT), '--base', 'HEAD~1', '--threshold', '5'],
        cwd=tmp_path, capture_output=True, text=True, encoding='utf-8', errors='replace',
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'b.py' in result.stdout
