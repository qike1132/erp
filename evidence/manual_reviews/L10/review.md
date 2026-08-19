# L10 前端与移动端人工审查

## 组件拆分
P1-5 拆分的 7 个巨型组件须 ≤ 400 行。

## 类型安全
.ts/.vue 须无 any 与 as any。

## 调试代码
须无裸 console.log(devLog 白名单除外)。

## 可访问性
图片有 alt / 交互元素有 aria-label / 表单有 label。

## Capacitor 配置
appId/appName/server.url 配置正确。

## 自动扫描结果
{
  "component_split": "scanned_vue_files: 282\nrefactored_components_status: all_split",
  "no_any": "scanned_ts_vue_files: 435",
  "no_console": "scanned_ts_vue_files: 438",
  "accessibility": "scanned_vue_files: 282",
  "capacitor_config": "appId: com.binfa.erp\nappName: 滨发ERP\nwebDir: dist\nserver_url: http://192.168.0.95:5002\nenv_capacitor_lines: 10"
}
