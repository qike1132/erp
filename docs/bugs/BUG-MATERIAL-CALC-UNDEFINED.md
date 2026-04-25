# BUG-MATERIAL-CALC-UNDEFINED 修复记录

- **修复时间**: 2026-04-23 10:31:44
- **Git Commit**: 215ee3c246501153bdfaa3313b3e5a71aa03a7c1
- **根因分析**: 前端 JS 从 API 响应中取 result.result（嵌套键），但后端返回扁平结构 {success, filling, fabric, accessory, packaging}，无 result 键，导致 calculationResults 为 undefined；后端 calculate_material 函数访问 mat.get('name','') 和 mat.get('quantity_per_unit',0) 但 to_dict() 返回的键名为 material_name 和 unit_usage，导致计算结果恒为 0 且名称为空
- **影响范围**: 物料用量计算页面 material_calculator.html 及后端 calculate_material 函数
- **修复方案**:
  1. 前端 material_calculator.html:1438 - 将 esult.result 改为显式提取 {filling, fabric, accessory, packaging} 并添加 || [] 空值 guard
  2. 后端 purchase_product_service.py:351 - mat.get('name','') 改为 mat.get('material_name','')
  3. 后端 purchase_product_service.py:353 - mat.get('quantity_per_unit',0) 改为 mat.get('unit_usage',0)
  4. 后端输出补充 material_name、specification、material_code 字段以匹配前端模板引用
- **验证结果**: L1 单元测试通过, 安全扫描 bandit 无高危, 77/79 现有测试通过（2个预先存在的失败与本次修复无关）
- **服务重启指南**: 服务运行在 192.168.0.95，需在部署后重启 FastAPI 服务使后端修改生效
