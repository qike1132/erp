"""渲染 ui_prototype_v8.html 的 8 个关键页面，输出高保真效果图 PNG。

用法: python _shoot_v8.py
输出: docs/ui-redesign/shots/NN_<page>.png
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE / "ui_prototype_v8.html"
OUT = HERE / "shots"
OUT.mkdir(exist_ok=True)

PAGES = [
    ("01_overview", "overview", "总览驾驶舱"),
    ("02_services", "services", "服务编排"),
    ("03_alerts", "alerts", "监控告警"),
    ("04_logs", "logs", "日志中心"),
    ("05_deploy", "deploy", "部署发布"),
    ("06_backup", "backup", "备份恢复"),
    ("07_config", "config", "配置中心"),
    ("08_access", "access", "权限与审计"),
]

VIEWPORT = {"width": 1600, "height": 1000}
errors = []


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(f"JS ERROR: {e}"))
        page.on("console", lambda m: errors.append(f"CONSOLE {m.type}: {m.text}")
                if m.type == "error" else None)

        page.goto(HTML.as_uri(), wait_until="load")
        page.wait_for_timeout(900)

        for slug, route, label in PAGES:
            # 点击对应导航项，触发真实交互
            page.click(f'.nav-item[data-page="{route}"]')
            page.wait_for_timeout(650)
            # 全页截图（含导航与顶栏），便于评审整体布局
            page.screenshot(path=str(OUT / f"{slug}.png"), full_page=True)
            print(f"  ✓ {slug}.png  ({label})")

        browser.close()

    if errors:
        print("\n发现页面错误:")
        for e in dict.fromkeys(errors):
            print("  -", e)
        return 1
    print("\n全部页面渲染成功，无 JS 错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
