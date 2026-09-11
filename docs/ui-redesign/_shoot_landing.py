"""渲染 v8-产品展示页效果图.html 并截图（桌面 + 移动端），同时捕获 JS 错误。"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE / "v8-产品展示页效果图.html"
OUT = HERE / "shots"
OUT.mkdir(exist_ok=True)

errors = []


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ---- 桌面全页 ----
        ctx = browser.new_context(viewport={"width": 1600, "height": 1000}, device_scale_factor=2)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(f"JS ERROR: {e}"))
        page.on("console", lambda m: errors.append(f"CONSOLE {m.type}: {m.text}")
                if m.type == "error" else None)

        page.goto(HTML.as_uri(), wait_until="load")
        page.wait_for_timeout(1200)
        # 触发全部进场动画
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1400)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(600)

        page.screenshot(path=str(OUT / "landing_desktop_full.png"), full_page=True)
        print("  landing_desktop_full.png  (桌面整页)")

        # 首屏
        page.screenshot(path=str(OUT / "landing_desktop_hero.png"))
        print("  landing_desktop_hero.png  (桌面首屏)")

        h = page.evaluate("document.body.scrollHeight")
        print(f"  桌面整页高度: {h}px")
        ctx.close()

        # ---- 移动端 ----
        ctx2 = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3,
                                   is_mobile=True, has_touch=True)
        m = ctx2.new_page()
        m.on("pageerror", lambda e: errors.append(f"JS ERROR(mobile): {e}"))
        m.goto(HTML.as_uri(), wait_until="load")
        m.wait_for_timeout(1000)
        # 展开汉堡菜单验证折叠导航
        m.click("#burger")
        m.wait_for_timeout(500)
        m.screenshot(path=str(OUT / "landing_mobile_menu.png"))
        print("  landing_mobile_menu.png   (移动端导航展开)")
        m.click("#burger")
        m.wait_for_timeout(400)
        m.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        m.wait_for_timeout(1200)
        m.evaluate("window.scrollTo(0, 0)")
        m.wait_for_timeout(500)
        m.screenshot(path=str(OUT / "landing_mobile_full.png"), full_page=True)
        print("  landing_mobile_full.png   (移动端整页)")

        # 检查是否有横向溢出
        ow = m.evaluate("document.documentElement.scrollWidth")
        print(f"  移动端 scrollWidth: {ow}px (视口 390，>390 即有横向溢出)")
        ctx2.close()
        browser.close()

    if errors:
        print("\n发现页面错误:")
        for e in dict.fromkeys(errors):
            print("  -", e)
        return 1
    print("\n渲染成功，无 JS 错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
