# 备货记录合并显示规格

## Why
当前备货管理页面中，相同客户和产品的多条备货记录分开独立显示，导致列表冗长且难以快速查看某客户某产品的总备货数量。用户需要将相同客户 + 产品的备货记录合并显示，同时在流水详情中保留各条原始记录的完整信息以便追溯。

## What Changes
- 合并相同客户名称 + 产品名称的备货记录
- 主表显示合并后的总备货数量
- 展开详情中显示各条原始备货记录的详细信息
- 保持数据的完整性和可追溯性
- 提供按客户 + 产品分组的视图

## Impact
- 受影响页面：`templates/stockin.html`
- 受影响后端：`app.py` - stockins 路由
- 用户体验：更清晰的备货汇总视图，同时保留详细追溯能力

## ADDED Requirements

### Requirement: 备货记录合并显示
系统 SHALL 将相同客户名称和产品名称的备货记录合并显示为一行：
- 合并条件：客户名称相同 AND 产品名称相同
- 显示字段：备货时间（最早）、客户名称、产品图片、产品名称、69 码、总数量、备注（首条）、操作
- 总数量 = 所有匹配记录的备货数量之和

#### Scenario: 合并显示
- **WHEN** 存在多条相同客户 + 产品的备货记录
- **THEN** 主表只显示一行，显示总数量
- **AND** 总数量使用醒目的徽章显示

### Requirement: 原始记录详情展示
系统 SHALL 在展开的流水详情中显示所有原始备货记录的完整信息：
- 每条原始记录的：备货编号、备货时间、备货数量、备注
- 按备货时间倒序排列
- 显示原始记录的数量统计

#### Scenario: 查看原始记录
- **WHEN** 用户点击展开按钮
- **THEN** 显示所有原始备货记录的详细信息
- **AND** 每条记录包含完整的追溯信息

### Requirement: 数据追溯能力
系统 SHALL 确保每条原始备货记录的关键信息可追溯：
- 备货编号（唯一标识）
- 备货时间
- 备货数量
- 备注信息
- 关联的抵扣流水记录

#### Scenario: 追溯原始记录
- **WHEN** 用户需要查看某条原始记录
- **THEN** 可在展开详情中找到完整信息
- **AND** 可追溯该记录的抵扣流水

## MODIFIED Requirements

### Requirement: 备货记录列表布局
修改后的表格列配置：
```
| 展开 | 备货时间 | 客户名称 | 产品图片 | 产品名称 | 69 码 | 总数量 | 备注 | 操作 |
```

### Requirement: 后端数据处理
后端 SHALL 在查询时进行分组聚合：
- 按客户名称 + 产品 ID 分组
- 聚合计算总数量
- 保留所有原始记录引用
- 预加载关联数据（产品图片、条码等）

## REMOVED Requirements

### Requirement: 独立显示每条备货记录
**Reason**: 列表冗长，不利于快速查看汇总信息
**Migration**: 原始记录信息在展开详情中完整保留

## Design Specifications

### 数据结构
```python
# 分组后的数据结构
{
    'customer': 'MINISO 国际',
    'product_id': 123,
    'product_name': '产品 A',
    'product_image': 'path/to/image.jpg',
    'barcode': '6942623811506',
    'total_quantity': 150,  # 合并后的总数
    'earliest_date': '2026-03-19',  # 最早的备货时间
    'note': '首条备注',
    'original_records': [  # 原始记录列表
        {
            'id': 1,
            'stockin_no': '2026-03-19-001',
            'stockin_date': '2026-03-19',
            'quantity': 100,
            'note': '第一批备货'
        },
        {
            'id': 2,
            'stockin_no': '2026-03-20-001',
            'stockin_date': '2026-03-20',
            'quantity': 50,
            'note': '第二批备货'
        }
    ]
}
```

### 色彩方案
遵循 ERP 系统 UI 设计规范：
- 总数量徽章：`bg-primary` (蓝色) - 突出显示
- 原始记录数量徽章：`bg-info` (青色) - 信息提示
- 其他字段保持原有样式

### 布局结构
```
主表格行 (tr)
├── 展开按钮 (td)
├── 备货时间 (td) - 显示最早的备货时间
├── 客户名称 (td)
├── 产品图片 (td)
├── 产品名称 (td)
├── 69 码 (td)
├── 总数量 (td) - 使用 badge 显示
├── 备注 (td) - 首条记录的备注
└── 操作 (td)
流水详情行 (tr.collapse)
└── 嵌套容器 (td colspan=9)
    └── 原始记录列表
        ├── 原始记录 1 (卡片/表格)
        │   ├── 备货编号
        │   ├── 备货时间
        │   ├── 备货数量
        │   └── 备注
        ├── 原始记录 2
        └── ...
```

### 交互说明
1. **展开/收起**：点击展开按钮，显示所有原始记录
2. **数量显示**：总数量使用大号徽章，原始记录数量使用小号徽章
3. **滚动优化**：原始记录区域最大高度 300px，超出可滚动
4. **空状态**：无原始记录时显示友好提示（理论上不会出现）

### 响应式考虑
- 小屏幕（<768px）：隐藏产品图片列
- 中等屏幕（768px-1024px）：显示主要信息
- 大屏幕（>1024px）：显示全部信息

## Technical Implementation

### 后端分组逻辑
```python
from collections import OrderedDict
from sqlalchemy.orm import joinedload

# 查询所有备货记录，预加载关联数据
stockins = StockIn.query.options(
    joinedload(StockIn.product),
    joinedload(StockIn.stockouts)
).all()

# 按客户 + 产品分组
grouped = OrderedDict()
for stockin in stockins:
    key = (stockin.customer, stockin.product_id)
    if key not in grouped:
        grouped[key] = {
            'customer': stockin.customer,
            'product': stockin.product,
            'product_id': stockin.product_id,
            'total_quantity': 0,
            'earliest_date': stockin.stockin_date,
            'note': stockin.note,
            'original_records': []
        }
    
    # 累加数量
    grouped[key]['total_quantity'] += stockin.quantity
    
    # 更新最早时间
    if stockin.stockin_date < grouped[key]['earliest_date']:
        grouped[key]['earliest_date'] = stockin.stockin_date
        grouped[key]['note'] = stockin.note
    
    # 添加原始记录
    grouped[key]['original_records'].append(stockin)
```

### 前端模板渲染
```html
{% for group_key, group in grouped_stockins.items() %}
<tr>
    <td>
        <button data-bs-toggle="collapse" data-bs-target="#detail-{{ loop.index }}">
            <i class="fas fa-chevron-down"></i>
        </button>
    </td>
    <td>{{ group.earliest_date.strftime('%Y-%m-%d') }}</td>
    <td>{{ group.customer }}</td>
    <td>
        {% if group.product.image %}
            <img src="{{ group.product.image }}" style="...">
        {% else %}
            -
        {% endif %}
    </td>
    <td>{{ group.product.name }}</td>
    <td>{{ group.product.barcode or '-' }}</td>
    <td>
        <span class="badge bg-primary">{{ group.total_quantity }}</span>
    </td>
    <td>{{ group.note or '-' }}</td>
    <td>
        <!-- 操作按钮 -->
    </td>
</tr>
<tr>
    <td colspan="9">
        <div class="collapse" id="detail-{{ loop.index }}">
            <div class="p-3" style="background: #F8F9FA;">
                <div class="d-flex align-items-center mb-3">
                    <i class="fas fa-list text-info me-2"></i>
                    <h6 class="mb-0 text-muted">原始记录 ({{ group.original_records|length }}条)</h6>
                </div>
                {% for record in group.original_records %}
                <div class="card mb-2">
                    <div class="card-body py-2">
                        <div class="row">
                            <div class="col-md-3">
                                <small class="text-muted">备货编号</small>
                                <p class="mb-0"><code>{{ record.stockin_no }}</code></p>
                            </div>
                            <div class="col-md-3">
                                <small class="text-muted">备货时间</small>
                                <p class="mb-0">{{ record.stockin_date.strftime('%Y-%m-%d') }}</p>
                            </div>
                            <div class="col-md-3">
                                <small class="text-muted">备货数量</small>
                                <p class="mb-0"><span class="badge bg-warning text-dark">{{ record.quantity }}</span></p>
                            </div>
                            <div class="col-md-3">
                                <small class="text-muted">备注</small>
                                <p class="mb-0">{{ record.note or '-' }}</p>
                            </div>
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
    </td>
</tr>
{% endfor %}
```

## Performance Considerations

### 查询优化
- 使用 `joinedload` 预加载产品和 stockouts 关联
- 避免 N+1 查询问题
- 分组操作在内存中进行，避免复杂 SQL

### 渲染优化
- 使用 `OrderedDict` 保持插入顺序
- 循环次数 = 分组数（远小于原始记录数）
- 展开详情懒加载（默认收起）

## Testing Requirements

### 功能测试
1. 相同客户 + 产品的记录正确合并
2. 总数量计算准确
3. 原始记录信息完整
4. 展开/收起功能正常

### 边界测试
1. 单条记录显示正常
2. 多条记录合并正确
3. 不同客户相同产品不合并
4. 相同客户不同产品不合并

### 数据验证
1. 总数量 = 各原始记录数量之和
2. 最早时间准确
3. 所有原始记录都在详情中显示
