"""T5 包化回归锁：dev_mode 模块（开发模式双进程管理,自持进程/模式状态）。

只读文本/AST,不 import UI 工具包 —— 保证 CI 可跑。
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DM = ROOT / "server_manager" / "dev_mode.py"
APP = ROOT / "server_manager" / "app.py"

# dev_mode 自持、且 app 侧仍有读写点的状态:一律经**读写双向**属性桥访问
# (缺哪一侧都会坏事)。`_startup_steps` 原在此列,但 app 侧 0 引用,T6 已随
# 4 个零引用委托一并裁剪(只留 app 真有读写点的 6 个)。
BRIDGES = ("_mode", "_process", "_frontend_process", "_current_mode_key",
           "_startup_progress", "_startup_current_step")

# 「按 (proc, name) 逐对终止」的循环 —— 迁后新拼写(旧名 self._frontend_process
# 在 dev_mode 里不存在,按旧拼写计数恒为 0,是空转锁;见 test_single_terminate_primitive)。
TERMINATE_LOOP = "for proc, name in ((self.frontend_process, '前端'), (self.process, '后端'))"


def _func_src(module: Path, name: str) -> str:
    """按 AST 取模块内某函数/方法的源码段(含缩进),不依赖文本顺序。"""
    src = module.read_text(encoding="utf-8")
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"{module.name} 内未找到 {name}")


def _app_bridge_src() -> dict[str, dict[str, str]]:
    """按 AST 取 ServerManagerApp 类体上的属性桥源码:{名字: {'getter': 段, 'setter': 段}}。

    只认类体上的装饰器:@property ⇒ getter,@<name>.setter ⇒ setter。
    """
    src = APP.read_text(encoding="utf-8")
    lines = src.splitlines()
    out: dict[str, dict[str, str]] = {}
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.ClassDef) and node.name == "ServerManagerApp"):
            continue
        for fn in node.body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            seg = "\n".join(lines[fn.lineno - 1 : fn.end_lineno])
            for dec in fn.decorator_list:
                if isinstance(dec, ast.Name) and dec.id == "property":
                    out.setdefault(fn.name, {})["getter"] = seg
                elif (isinstance(dec, ast.Attribute) and dec.attr == "setter"
                      and isinstance(dec.value, ast.Name)):
                    out.setdefault(dec.value.id, {})["setter"] = seg
    return out


def test_module_exists_and_is_tk_free() -> None:
    text = DM.read_text(encoding="utf-8")
    assert "tkinter" not in text
    assert "from server_manager.app" not in text


def test_class_owns_state() -> None:
    text = DM.read_text(encoding="utf-8")
    assert "class DevModeOps" in text
    for attr in ("self.process", "self.frontend_process", "self.mode", "self.current_mode_key"):
        assert attr in text, f"DevModeOps 应自持 {attr}"


def test_single_terminate_primitive() -> None:
    """B4 回归锁随之迁移(T5):dev_mode 内「逐对终止」循环恰好一处。

    ★ 必须用**迁后新拼写**计数。旧写法 ``self.count("for proc, name in ((self._frontend_process")``
    在 dev_mode 内恒为 0(该名字已改名),即便有人复制第二份终止循环也照样绿 —— 空转锁
    (2026-09-28 评审)。本条按新拼写数,任何形式的复制都会让计数 >1 而变红。
    """
    n = DM.read_text(encoding="utf-8").count(TERMINATE_LOOP)
    assert n == 1, f"dev_mode 内开发进程终止循环出现 {n} 处(应恰好 1 处)"
    # 该唯一循环必须落在统一原语内,并复用 kill_process_tree(而非另起一套终止手段)
    body = _func_src(DM, "terminate_dev_processes")
    assert TERMINATE_LOOP in body, "终止循环不在统一原语 terminate_dev_processes 内"
    assert "kill_process_tree" in body, "统一原语未复用 kill_process_tree"


def test_app_bridges_state() -> None:
    """app 侧必须以**读写双向**属性桥暴露 dev_mode 自持的 6 个状态。

    只查 getter 等于只锁一半:缺 setter 时每次写入都会 AttributeError(或被迫绕过桥),
    而 UI 崩溃检测(check_server_status / _update_all_ui)正是靠这些状态的读写点工作。
    故对 6 个名字**逐个**断言 getter(@property)与 setter(@<name>.setter)都在,
    且二者确实路由到 dev_mode 的同名状态(self.dev.<attr>)。
    """
    bridges = _app_bridge_src()
    for name in BRIDGES:
        attr = name.lstrip("_")
        entry = bridges.get(name, {})
        getter, setter = entry.get("getter"), entry.get("setter")
        assert getter is not None, f"app.py 缺属性桥 getter @property def {name}"
        assert setter is not None, f"app.py 缺属性桥 setter @{name}.setter —— 写入会 AttributeError"
        assert f"return self.dev.{attr}" in getter, f"{name} getter 未路由到 dev.{attr}"
        assert f"self.dev.{attr} = value" in setter, f"{name} setter 未路由到 dev.{attr}"
