import os

dst = r'd:\erp_system\frontend-vite\src\views\production\ProductionView.vue'
with open(dst, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("for (const dept of ['filling', 'handcraft', 'packaging'])", "for (const dept of ['filling', 'handcraft'])")

with open(dst, 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed deptStats loop')
