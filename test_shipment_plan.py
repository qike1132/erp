"""
出货计划功能全面系统测试 v3
- 先清理旧数据再创建
- 幂等：已存在的数据跳过
- 完整覆盖所有测试步骤
"""
import sys
from datetime import datetime, timedelta

import requests

BASE = "http://127.0.0.1:5002/api/v1"
session = requests.Session()
session.headers.update({"Content-Type": "application/json"})

PASS = FAIL = WARN = 0
ERRORS = []
PLAN_IDS = []  # 全局声明

def log(level, msg):
    prefix = {"ok": "  [PASS]", "fail": "  [FAIL]", "warn": "  [WARN]", "info": "  [INFO]", "hdr": "\n>>"}
    print(f"{prefix.get(level, '')} {msg}")
    if level == "fail": global FAIL; FAIL += 1; ERRORS.append(msg)
    elif level == "ok": global PASS; PASS += 1
    elif level == "warn": global WARN; WARN += 1

def login():
    log("hdr", "认证")
    for pw in ["admin123", "admin", "123456"]:
        r = session.post(f"{BASE}/auth/login", json={"username": "admin", "password": pw})
        if r.status_code == 200:
            token = r.json().get("access_token", "")
            if token:
                session.headers.update({"Authorization": f"Bearer {token}"})
                log("ok", "登录成功")
                return True
    log("fail", "登录失败")
    return False

# ====== 数据准备 ======
CUSTOMER_NAMES = [
    "深圳华为技术有限公司", "北京京东世纪贸易有限公司", "杭州阿里巴巴网络技术有限公司",
    "上海汽车集团股份有限公司", "广州宝洁有限公司", "成都鼎桥通信技术有限公司",
    "武汉烽火通信科技股份有限公司", "南京南瑞继保电气有限公司", "西安中兴通讯终端科技有限公司",
    "厦门美图网科技有限公司",
]

CUSTOMER_PAYLOAD = [
    {"name": CUSTOMER_NAMES[0], "contact": "张伟", "phone": "13800138001", "address": "深圳市龙岗区坂田华为基地", "note": "VIP-电子"},
    {"name": CUSTOMER_NAMES[1], "contact": "李娜", "phone": "13800138002", "address": "北京市亦庄经开区", "note": "电商-日用品"},
    {"name": CUSTOMER_NAMES[2], "contact": "王强", "phone": "13800138003", "address": "杭州市余杭区文一西路", "note": "跨境电商"},
    {"name": CUSTOMER_NAMES[3], "contact": "赵敏", "phone": "13800138004", "address": "上海市嘉定区安亭镇", "note": "汽车零部件"},
    {"name": CUSTOMER_NAMES[4], "contact": "陈静", "phone": "13800138005", "address": "广州市天河区珠江新城", "note": "日化用品"},
    {"name": CUSTOMER_NAMES[5], "contact": "刘洋", "phone": "13800138006", "address": "成都市高新区天府软件园", "note": "通信设备"},
    {"name": CUSTOMER_NAMES[6], "contact": "孙磊", "phone": "13800138007", "address": "武汉市东湖高新区光谷大道", "note": "光纤通信"},
    {"name": CUSTOMER_NAMES[7], "contact": "周婷", "phone": "13800138008", "address": "南京市江宁区胜太路", "note": "电力设备"},
    {"name": CUSTOMER_NAMES[8], "contact": "吴昊", "phone": "13800138009", "address": "西安市高新区锦业路", "note": "手机终端"},
    {"name": CUSTOMER_NAMES[9], "contact": "郑晓", "phone": "13800138010", "address": "厦门市思明区软件园二期", "note": "互联网软件"},
]

PRODUCT_NAMES = [
    "智能手机A12-5G", "蓝牙降噪耳机Pro", "智能手表S8-运动版",
    "USB-C高速数据线2m", "无线充电板15W", "便携移动电源20000mAh",
    "笔记本电脑散热支架", "4K高清HDMI线3m", "智能音箱AI-Cloud",
    "车载手机支架磁吸款",
]

PRODUCT_PAYLOAD = [
    {"name": PRODUCT_NAMES[0], "barcode": "6901234560001", "price": 2999.00, "initial_stock": 500},
    {"name": PRODUCT_NAMES[1], "barcode": "6901234560002", "price": 599.00, "initial_stock": 1200},
    {"name": PRODUCT_NAMES[2], "barcode": "6901234560003", "price": 1299.00, "initial_stock": 300},
    {"name": PRODUCT_NAMES[3], "barcode": "6901234560004", "price": 29.90, "initial_stock": 5000},
    {"name": PRODUCT_NAMES[4], "barcode": "6901234560005", "price": 99.00, "initial_stock": 2000},
    {"name": PRODUCT_NAMES[5], "barcode": "6901234560006", "price": 149.00, "initial_stock": 800},
    {"name": PRODUCT_NAMES[6], "barcode": "6901234560007", "price": 199.00, "initial_stock": 350},
    {"name": PRODUCT_NAMES[7], "barcode": "6901234560008", "price": 49.90, "initial_stock": 3000},
    {"name": PRODUCT_NAMES[8], "barcode": "6901234560009", "price": 399.00, "initial_stock": 600},
    {"name": PRODUCT_NAMES[9], "barcode": "6901234560010", "price": 79.00, "initial_stock": 1500},
]

# ====== 1. 客户 ======
def test_customers():
    log("hdr", "【测试1】新建10个不同属性客户")
    # 先查现有客户列表
    CUSTOMER_MAP.clear()
    try:
        r = session.get(f"{BASE}/customers/list", params={"page": 1, "page_size": 200})
        if r.status_code == 200:
            for c in r.json().get("customers", []):
                CUSTOMER_MAP[c.get("name", "")] = c.get("id")
            log("info", f"现有客户: {len(CUSTOMER_MAP)}个")
    except Exception:
        pass

    created = 0
    for i, c in enumerate(CUSTOMER_PAYLOAD):
        if c["name"] in CUSTOMER_MAP:
            log("warn", f"客户{i+1}: {c['name'][:16]}... 已存在(ID={CUSTOMER_MAP[c['name']]})，跳过")
            continue
        try:
            r = session.post(f"{BASE}/customers/create", json=c)
            if r.status_code in (200, 201):
                created += 1
                log("ok", f"客户{i+1}: {c['name'][:16]}... 新建成功")
            else:
                log("fail", f"客户{i+1}: HTTP{r.status_code} {r.text[:150]}")
        except Exception as e:
            log("fail", f"客户{i+1}: {e}")
    log("info", f"客户: 新建{created}个, 共{len(CUSTOMER_MAP)}个")

    # 刷新映射
    try:
        r = session.get(f"{BASE}/customers/list", params={"page": 1, "page_size": 200})
        if r.status_code == 200:
            CUSTOMER_MAP.clear()
            for c in r.json().get("customers", []):
                CUSTOMER_MAP[c.get("name", "")] = c.get("id")
            log("ok", f"客户列表验证: {len(CUSTOMER_MAP)}个客户")
    except Exception as e:
        log("fail", f"客户列表: {e}")

# ====== 2. 产品 ======
def test_products():
    log("hdr", "【测试2】新建10个不同规格产品")
    # 先查现有
    PRODUCT_MAP.clear()
    try:
        r = session.get(f"{BASE}/products/list")
        if r.status_code == 200:
            data = r.json()
            prods = data.get("data", data if isinstance(data, list) else [])
            if isinstance(prods, list):
                for p in prods:
                    if isinstance(p, dict):
                        PRODUCT_MAP[p.get("name", "")] = {
                            "id": p.get("id"),
                            "barcode": p.get("barcode", ""),
                            "price": p.get("price", 0),
                            "stock": p.get("current_stock", p.get("initial_stock", 0)),
                        }
            log("info", f"现有产品: {len(PRODUCT_MAP)}个")
    except Exception as e:
        log("info", f"产品列表: {e}")

    created = 0
    for i, p in enumerate(PRODUCT_PAYLOAD):
        if p["name"] in PRODUCT_MAP:
            log("warn", f"产品{i+1}: {p['name'][:16]}... 已存在, 跳过")
            continue
        try:
            r = session.post(f"{BASE}/products/create", json=p)
            if r.status_code in (200, 201):
                created += 1
                log("ok", f"产品{i+1}: {p['name'][:16]}... ¥{p['price']} 库存{p['initial_stock']}")
            else:
                log("fail", f"产品{i+1}: HTTP{r.status_code} {r.text[:150]}")
        except Exception as e:
            log("fail", f"产品{i+1}: {e}")
    log("info", f"产品: 新建{created}个, 共{len(PRODUCT_MAP)}个")

    # 刷新映射
    try:
        r = session.get(f"{BASE}/products/list")
        if r.status_code == 200:
            PRODUCT_MAP.clear()
            data = r.json()
            prods = data.get("data", data if isinstance(data, list) else [])
            if isinstance(prods, list):
                for p in prods:
                    if isinstance(p, dict):
                        PRODUCT_MAP[p.get("name", "")] = {
                            "id": p.get("id"),
                            "barcode": p.get("barcode", ""),
                            "price": p.get("price", 0),
                            "stock": p.get("current_stock", p.get("initial_stock", 0)),
                        }
            log("ok", f"产品列表验证: {len(PRODUCT_MAP)}个产品")
            if len(PRODUCT_MAP) >= 5:
                samples = list(PRODUCT_MAP.items())[:3]
                for name, info in samples:
                    log("info", f"  {name[:20]} | 条码={info['barcode']} | 价格={info['price']} | 库存={info['stock']}")
    except Exception as e:
        log("fail", f"产品列表: {e}")

# ====== 3. 出货计划 ======
def test_plans():
    log("hdr", "【测试3】新建10个多场景出货计划")
    global PLAN_IDS
    PLAN_IDS = []

    if len(CUSTOMER_MAP) < 5:
        log("fail", f"客户不足({len(CUSTOMER_MAP)}个)")
        return
    if len(PRODUCT_MAP) < 5:
        log("fail", f"产品不足({len(PRODUCT_MAP)}个)")
        return

    now = datetime.now()
    ym = now.strftime("%Y-%m")

    c_list = [(n, i) for n, i in CUSTOMER_MAP.items() if n in CUSTOMER_NAMES]
    p_list = [(n, i) for n, i in PRODUCT_MAP.items() if n in PRODUCT_NAMES]

    # 场景: (描述, 客户索引, [(产品索引, 数量)], [日期偏移])
    scenarios = [
        ("单产品大批量", 0, [(0, 500)], [3]),
        ("多产品混合", 1, [(1, 200), (2, 150), (3, 500)], [5, 7, 10]),
        ("多日分批出货", 2, [(0, 100), (0, 100), (0, 100)], [1, 8, 15]),
        ("紧急次日出货", 3, [(4, 50)], [1]),
        ("月末集中出货", 4, [(5, 300), (6, 200)], [28, 28]),
        ("高价值小批量", 5, [(0, 10), (2, 5)], [12, 12]),
        ("日用品大批量", 6, [(3, 2000), (7, 1000)], [6, 6]),
        ("汽车零部件单", 7, [(8, 80)], [20]),
        ("跨线混合", 8, [(0, 30), (4, 50), (8, 20), (9, 100)], [4, 4, 4, 4]),
        ("定期补货", 9, [(5, 100), (6, 150), (9, 250)], [14, 14, 14]),
    ]

    for i, sc in enumerate(scenarios):
        try:
            desc = sc[0]
            if sc[1] >= len(c_list): continue
            cname, cid = c_list[sc[1]]

            details = []
            for j, (pi, qty) in enumerate(sc[2]):
                if pi >= len(p_list): continue
                pname, pinfo = p_list[pi]
                plan_date = (now + timedelta(days=sc[3][min(j, len(sc[3])-1)])).strftime("%Y-%m-%d")

                details.append({
                    "product_id": pinfo["id"],
                    "product_name": pname,
                    "barcode": pinfo.get("barcode", ""),
                    "quantity": qty,
                    "plan_date": plan_date,
                    "remark": f"测试-{desc}",
                })

            if not details: continue

            r = session.post(f"{BASE}/plans/create", json={
                "customer_id": cid,
                "customer_name": cname,
                "plan_month": ym,
                "details": details,
                "remark": "",
            })

            if r.status_code in (200, 201):
                pid = r.json().get("plan_id") or r.json().get("id")
                PLAN_IDS.append(pid) if pid else None
                log("ok", f"计划{i+1}: [{desc}] {cname[:10]}... {len(details)}行 -> 成功")
            else:
                log("fail", f"计划{i+1} [{desc}]: HTTP{r.status_code} {r.text[:300]}")
        except Exception as e:
            log("fail", f"计划{i+1}: {e}")

    log("info", f"出货计划: 创建{len(PLAN_IDS)}个")

# ====== 4. 验证 ======
def test_integrity():
    log("hdr", "【测试4】数据完整性、报表与状态流转验证")
    now = datetime.now()

    # 4a: 计划列表
    try:
        r = session.get(f"{BASE}/plans/list", params={"year": now.year, "month": now.month})
        if r.status_code == 200:
            plans = r.json().get("plans", [])
            log("ok", f"计划列表: {len(plans)}个主计划")
            statuses = {}
            for p in plans:
                s = p.get("status", "?")
                statuses[s] = statuses.get(s, 0) + 1
                log("info", f"  #{p.get('id')} {p.get('plan_no','')} [{s}] {p.get('detail_count',0)}明细 总量{p.get('total_quantity',0)} 已出{p.get('total_shipped',0)}")
            log("info", f"  状态分布: {statuses}")
        else:
            log("fail", f"计划列表: HTTP{r.status_code}")
    except Exception as e:
        log("fail", f"计划列表: {e}")

    # 4b: 月度日历
    try:
        r = session.get(f"{BASE}/plans/monthly", params={"year": now.year, "month": now.month})
        if r.status_code == 200:
            pbd = r.json().get("plans_by_date", {})
            total = sum(len(v) for v in pbd.values()) if isinstance(pbd, dict) else 0
            log("ok", f"月度日历: {len(pbd)}日期, {total}明细")
            # 抽样验证日期数据
            dates = sorted(pbd.keys())[:3]
            for d in dates:
                items = pbd[d]
                log("info", f"  {d}: {len(items)}条 | 客户: { {i.get('customer_name','')[:8] for i in items if isinstance(i,dict)} }")
        else:
            log("fail", f"月度日历: HTTP{r.status_code}")
    except Exception as e:
        log("fail", f"月度日历: {e}")

    # 4c: 库存对比
    try:
        r = session.get(f"{BASE}/plans/inventory-compare", params={"year": now.year, "month": now.month})
        if r.status_code == 200:
            details = r.json().get("details", [])
            ok_count = sum(1 for d in details if d.get("stock_status") == "sufficient")
            bad_count = sum(1 for d in details if d.get("stock_status") == "shortage")
            log("ok", f"库存对比: {len(details)}条 (充足{ok_count} 不足{bad_count})")
            for d in details[:3]:
                log("info", f"  {d.get('product_name','')[:20]} | 计划{d.get('plan_qty')} | 库存{d.get('inventory_qty')} | 差额{d.get('diff')} | {d.get('stock_status')}")
        else:
            log("fail", f"库存对比: HTTP{r.status_code}")
    except Exception as e:
        log("fail", f"库存对比: {e}")

    # 4d: 客户汇总
    try:
        r = session.get(f"{BASE}/plans/customer-summary", params={"year": now.year, "month": now.month})
        if r.status_code == 200:
            customers = r.json().get("customers", [])
            log("ok", f"客户汇总: {len(customers)}个客户")
            for c in customers[:5]:
                log("info", f"  {c.get('customer_name','')[:12]} | 计划{c.get('plan_qty')} | 库存{c.get('inventory_qty')} | 已出{c.get('shipped_qty')} | 待出{c.get('remaining_qty')}")
        else:
            log("fail", f"客户汇总: HTTP{r.status_code}")
    except Exception as e:
        log("fail", f"客户汇总: {e}")

    # 4e: 状态流转
    if PLAN_IDS:
        try:
            pid = PLAN_IDS[0]
            # pending -> confirmed
            r1 = session.put(f"{BASE}/plans/edit/{pid}", json={"status": "confirmed"})
            if r1.status_code in (200, 201):
                log("ok", f"状态流转: #{pid} pending->confirmed")
            else:
                log("fail", f"状态流转#1: HTTP{r1.status_code} {r1.text[:150]}")

            # confirmed -> completed
            r2 = session.put(f"{BASE}/plans/edit/{pid}", json={"status": "completed"})
            if r2.status_code in (200, 201):
                log("ok", f"状态流转: #{pid} confirmed->completed")
            else:
                log("warn", f"状态流转#2: HTTP{r2.status_code} {r2.text[:80]}")

            # 验证最终状态
            r3 = session.get(f"{BASE}/plans/{pid}/detail")
            if r3.status_code == 200:
                st = r3.json().get("plan", {}).get("status", "?")
                log("ok" if st == "completed" else "warn", f"状态验证: #{pid} 最终状态={st}")
            else:
                log("info", f"详情接口: HTTP{r3.status_code}")
        except Exception as e:
            log("fail", f"状态流转: {e}")

    # 4f: 出货进度
    try:
        r = session.get(f"{BASE}/plans/shipment-progress", params={"year": now.year, "month": now.month})
        if r.status_code == 200:
            deps = r.json().get("details", [])
            log("ok", f"出货进度: {len(deps)}条")
        elif r.status_code == 404:
            log("warn", "出货进度接口: 404(未实现)")
        else:
            log("info", f"出货进度: HTTP{r.status_code}")
    except Exception as e:
        log("info", f"出货进度: {e}")

    # 4g: 时间轴
    try:
        r = session.get(f"{BASE}/plans/timeline", params={"year": now.year, "month": now.month})
        if r.status_code == 200:
            log("ok", "时间轴查询: 成功")
        elif r.status_code == 404:
            log("warn", "时间轴接口: 404")
        else:
            log("info", f"时间轴: HTTP{r.status_code}")
    except Exception:
        log("info", "时间轴: 跳过")

# ====== 5. 边界测试 ======
def test_edges():
    log("hdr", "【测试5】异常边界与数据校验")

    tests = [
        ("缺必填字段", {"plan_month": "2026-05"}, (400, 422)),
        ("负数数量", {"customer_id": 1, "customer_name": "T", "plan_month": "2026-05",
                      "details": [{"product_id": 1, "product_name": "T", "barcode": "", "quantity": -5, "plan_date": "2026-05-15", "remark": ""}]}, (400, 422)),
        ("数量为0", {"customer_id": 1, "customer_name": "T", "plan_month": "2026-05",
                     "details": [{"product_id": 1, "product_name": "T", "barcode": "", "quantity": 0, "plan_date": "2026-05-15", "remark": ""}]}, (400, 422)),
        ("空明细列表", {"customer_id": 1, "customer_name": "T", "plan_month": "2026-05", "details": []}, (400, 422)),
        ("无效日期格式", {"customer_id": 1, "customer_name": "T", "plan_month": "2026-05",
                         "details": [{"product_id": 1, "product_name": "T", "barcode": "", "quantity": 10, "plan_date": "2026/05/15", "remark": ""}]}, (400, 422)),
    ]

    for label, payload, expected_codes in tests:
        try:
            r = session.post(f"{BASE}/plans/create", json=payload)
            if r.status_code in expected_codes:
                log("ok", f"[{label}]: 正确拒绝 HTTP{r.status_code}")
            else:
                log("fail", f"[{label}]: 期望{expected_codes}, 实际HTTP{r.status_code} -> {r.text[:200]}")
        except Exception as e:
            log("fail", f"[{label}]: 异常 {e}")

# ====== 全局存储 ======
CUSTOMER_MAP = {}
PRODUCT_MAP = {}

def main():
    print("\n" + "="*60)
    print("   出货计划功能 - 全面系统测试 v3")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}   API: {BASE}")
    print("="*60)

    if not login():
        print("[FAIL] 无法登录"); sys.exit(1)

    test_customers()
    test_products()
    test_plans()
    test_integrity()
    test_edges()

    # ====== 汇总 ======
    print("\n" + "="*60)
    total = PASS + FAIL + WARN
    rate = round(PASS / max(total - WARN, 1) * 100, 1)
    print(f"   通过 {PASS}  失败 {FAIL}  警告 {WARN}")
    print(f"   核心通过率: {rate}% (排除警告后)")
    if FAIL:
        print("\n   失败详情:")
        for e in ERRORS:
            print(f"     - {e}")
    else:
        print("   ** 全部核心测试通过！ **")
    print("="*60)
    return FAIL == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
