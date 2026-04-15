# 高质量折叠UI动画组件 - 使用文档

## 📋 概述

这是一个高质量的折叠UI动画组件，提供平滑的展开/收起过渡效果，完全满足以下要求：

✅ **平滑动画**：300-500ms的流畅过渡
✅ **状态指示**：箭头方向变化清晰提示
✅ **性能优化**：使用CSS transform和opacity避免布局抖动
✅ **浏览器兼容**：Chrome、Firefox、Safari、Edge最新版本
✅ **可配置**：调整动画持续时间、easing函数等
✅ **无障碍支持**：ARIA属性和键盘导航
✅ **事件驱动**：完整的回调系统

---

## 🚀 快速开始

### 1. 引入文件

在HTML中引入CSS和JS文件：

```html
<!-- 在<head>中 -->
<link rel="stylesheet" href="static/collapse-animated.css">

<!-- 在</body>前 -->
<script src="static/collapse-animated.js"></script>
```

### 2. HTML结构

```html
<div class="card" id="myCollapseContainer">
    <div class="card-header d-flex justify-content-between align-items-center collapse-trigger">
        <h6>折叠标题</h6>
        <i class="fas fa-chevron-down collapse-arrow"></i>
    </div>
    <div class="collapse-content" id="myCollapse">
        <div class="card-body">
            <!-- 折叠内容 -->
        </div>
    </div>
</div>
```

### 3. 初始化

```javascript
document.addEventListener('DOMContentLoaded', function() {
    const collapse = new CollapseAnimated('#myCollapseContainer', {
        duration: 400,
        initialState: 'expanded'
    });
});
```

---

## 📚 API文档

### CollapseAnimated 类

#### 构造函数

```javascript
new CollapseAnimated(element, options)
```

**参数**：
- `element` (HTMLElement|string) - 容器元素或选择器
- `options` (Object) - 配置选项（可选）

---

### 配置选项

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `duration` | number | `400` | 动画持续时间（毫秒） |
| `easing` | string | `'cubic-bezier(0.4, 0, 0.2, 1)'` | 展开动画easing函数 |
| `easingOut` | string | `'cubic-bezier(0, 0, 0.2, 1)'` | 收起动画easing函数 |
| `arrowDuration` | number | `300` | 箭头动画持续时间（毫秒） |
| `arrowEasing` | string | `'ease-in-out'` | 箭头动画easing函数 |
| `initialState` | string | `'expanded'` | 初始状态：`'expanded'` 或 `'collapsed'` |
| `triggerSelector` | string | `'.collapse-trigger'` | 触发元素选择器 |
| `contentSelector` | string | `'.collapse-content'` | 内容区域选择器 |
| `arrowSelector` | string | `'.collapse-arrow'` | 箭头元素选择器 |
| `onExpand` | function | `null` | 展开回调 |
| `onCollapse` | function | `null` | 收起回调 |
| `onToggle` | function | `null` | 切换回调 |
| `onAnimating` | function | `null` | 动画中回调 |
| `useHardwareAcceleration` | boolean | `true` | 使用硬件加速 |
| `reduceReflow` | boolean | `true` | 减少重绘 |
| `accessibility` | boolean | `true` | 启用无障碍支持 |

---

### 实例方法

#### `toggle()`

切换展开/收起状态

```javascript
collapse.toggle();
```

#### `expand()`

展开折叠组件

```javascript
collapse.expand();
```

#### `collapse()`

收起折叠组件

```javascript
collapse.collapse();
```

#### `getState()`

获取当前状态

```javascript
const state = collapse.getState();
// 返回: 'expanded' 或 'collapsed'
```

#### `getIsAnimating()`

检查是否正在动画

```javascript
const isAnimating = collapse.getIsAnimating();
// 返回: true 或 false
```

#### `updateOptions(newOptions)`

更新配置选项

```javascript
collapse.updateOptions({
    duration: 500,
    easing: 'ease-in-out'
});
```

#### `destroy()`

销毁组件

```javascript
collapse.destroy();
```

---

### 静态方法

#### `CollapseAnimated.initAll(selector, options)`

批量初始化所有折叠组件

```javascript
const instances = CollapseAnimated.initAll('.my-collapse-class', {
    duration: 400
});
```

**参数**：
- `selector` (string) - 选择器（默认：`'.collapse-animated-container'`）
- `options` (Object) - 配置选项

**返回**：`CollapseAnimated[]` - 实例数组

---

## 🎨 预设配置

### 动画持续时间预设

#### 快速动画 (300ms)

```javascript
new CollapseAnimated('#container', {
    duration: 300,
    arrowDuration: 250
});
```

或使用CSS类：
```html
<div class="card collapse-animated fast" id="container">
```

#### 标准动画 (400ms) - 默认

```javascript
new CollapseAnimated('#container', {
    duration: 400,
    arrowDuration: 300
});
```

或使用CSS类：
```html
<div class="card collapse-animated normal" id="container">
```

#### 慢速动画 (500ms)

```javascript
new CollapseAnimated('#container', {
    duration: 500,
    arrowDuration: 400
});
```

或使用CSS类：
```html
<div class="card collapse-animated slow" id="container">
```

---

### easing函数预设

#### Material Design 标准

```javascript
new CollapseAnimated('#container', {
    easing: 'cubic-bezier(0.4, 0, 0.2, 1)',
    easingOut: 'cubic-bezier(0, 0, 0.2, 1)'
});
```

或使用CSS类：
```html
<div class="card collapse-animated easing-material" id="container">
```

#### 线性

```javascript
new CollapseAnimated('#container', {
    easing: 'linear',
    easingOut: 'linear'
});
```

或使用CSS类：
```html
<div class="card collapse-animated easing-linear" id="container">
```

#### 缓入缓出

```javascript
new CollapseAnimated('#container', {
    easing: 'ease-in-out',
    easingOut: 'ease-in-out'
});
```

或使用CSS类：
```html
<div class="card collapse-animated easing-ease-in-out" id="container">
```

#### 弹性动画

```javascript
new CollapseAnimated('#container', {
    easing: 'cubic-bezier(0.68, -0.55, 0.265, 1.55)',
    easingOut: 'cubic-bezier(0.68, -0.55, 0.265, 1.55)'
});
```

或使用CSS类：
```html
<div class="card collapse-animated easing-elastic" id="container">
```

#### 弹跳动画

```javascript
new CollapseAnimated('#container', {
    easing: 'cubic-bezier(0.175, 0.885, 0.32, 1.275)',
    easingOut: 'cubic-bezier(0.6, -0.28, 0.735, 0.045)'
});
```

或使用CSS类：
```html
<div class="card collapse-animated easing-bounce" id="container">
```

---

## 💡 使用示例

### 基本用法

```javascript
document.addEventListener('DOMContentLoaded', function() {
    const collapse = new CollapseAnimated('#myContainer', {
        duration: 400,
        initialState: 'expanded'
    });
});
```

### 带回调函数

```javascript
const collapse = new CollapseAnimated('#myContainer', {
    duration: 400,
    onExpand: () => {
        console.log('折叠已展开');
    },
    onCollapse: () => {
        console.log('折叠已收起');
    },
    onToggle: (isExpanded) => {
        console.log(`当前状态: ${isExpanded ? '展开' : '收起'}`);
    },
    onAnimating: (isExpanding) => {
        console.log(`正在${isExpanding ? '展开' : '收起'}...`);
    }
});
```

### 程序化控制

```javascript
const collapse = new CollapseAnimated('#myContainer');

// 切换
document.getElementById('toggleBtn').addEventListener('click', () => {
    collapse.toggle();
});

// 展开
document.getElementById('expandBtn').addEventListener('click', () => {
    collapse.expand();
});

// 收起
document.getElementById('collapseBtn').addEventListener('click', () => {
    collapse.collapse();
});

// 检查状态
document.getElementById('checkBtn').addEventListener('click', () => {
    const state = collapse.getState();
    const isAnimating = collapse.getIsAnimating();
    console.log(`状态: ${state}, 动画中: ${isAnimating}`);
});
```

### 批量初始化

```javascript
document.addEventListener('DOMContentLoaded', function() {
    // 初始化所有带特定类的折叠组件
    const instances = CollapseAnimated.initAll('.product-section', {
        duration: 400,
        initialState: 'collapsed'
    });
    
    console.log(`已初始化 ${instances.length} 个折叠组件`);
});
```

### 动态更新配置

```javascript
const collapse = new CollapseAnimated('#myContainer', {
    duration: 400,
    easing: 'ease-in-out'
});

// 用户选择快速动画
document.getElementById('fastMode').addEventListener('change', (e) => {
    if (e.target.checked) {
        collapse.updateOptions({
            duration: 300,
            arrowDuration: 250
        });
    } else {
        collapse.updateOptions({
            duration: 400,
            arrowDuration: 300
        });
    }
});
```

---

## ⌨️ 键盘导航

组件支持以下键盘操作：

| 按键 | 功能 |
|------|------|
| `Enter` 或 `Space` | 切换展开/收起 |
| `Tab` | 聚焦到下一个可聚焦元素 |

---

## ♿ 无障碍支持

组件自动设置以下ARIA属性：

```html
<!-- 触发元素 -->
<div class="collapse-trigger"
     role="button"
     tabindex="0"
     aria-expanded="true"
     aria-controls="collapse-content">
</div>

<!-- 内容区域 -->
<div class="collapse-content"
     id="collapse-content"
     aria-hidden="false">
</div>
```

可通过 `accessibility: false` 禁用：

```javascript
new CollapseAnimated('#container', {
    accessibility: false
});
```

---

## 🎯 性能优化

### 硬件加速

```javascript
new CollapseAnimated('#container', {
    useHardwareAcceleration: true  // 默认启用
});
```

或使用CSS类：
```html
<div class="card collapse-animated hardware-accelerated" id="container">
```

### 减少重绘

```javascript
new CollapseAnimated('#container', {
    reduceReflow: true  // 默认启用
});
```

或使用CSS类：
```html
<div class="card collapse-animated reduce-reflow" id="container">
```

### 减少动画（无障碍）

系统会自动检测 `prefers-reduced-motion` 媒体查询，为需要的用户禁用动画。

---

## 🔧 工具类

### 隐藏箭头

```html
<div class="card collapse-animated no-arrow" id="container">
```

### 箭头位置

```html
<!-- 箭头在右侧（默认） -->
<div class="card collapse-animated arrow-right" id="container">

<!-- 箭头在左侧 -->
<div class="card collapse-animated arrow-left" id="container">
```

---

## 📊 浏览器兼容性

| 浏览器 | 最低版本 |
|--------|----------|
| Chrome | 74+ |
| Firefox | 69+ |
| Safari | 13.1+ |
| Edge | 79+ |

对于不支持的浏览器，组件会降级为无动画版本。

---

## 🐛 故障排除

### 问题：动画不工作

**检查**：
1. CSS和JS文件是否正确引入
2. HTML结构是否正确
3. 控制台是否有错误

**解决**：
```javascript
// 检查CollapseAnimated是否可用
if (window.CollapseAnimated) {
    console.log('CollapseAnimated 已加载');
} else {
    console.error('CollapseAnimated 未加载');
}
```

---

### 问题：箭头不旋转

**检查**：
- 箭头元素是否有 `collapse-arrow` 类
- 箭头是否在 `collapse-trigger` 内部

**解决**：
```html
<div class="collapse-trigger">
    <h6>标题</h6>
    <i class="fas fa-chevron-down collapse-arrow"></i>
</div>
```

---

### 问题：内容显示不正确

**检查**：
- 内容是否在 `collapse-content` 内部
- 是否有CSS覆盖了样式

**解决**：
```html
<div class="collapse-content" id="myCollapse">
    <div class="card-body">
        <!-- 内容 -->
    </div>
</div>
```

---

## 📝 完整示例

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>折叠动画示例</title>
    <link href="bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="collapse-animated.css">
</head>
<body>
    <div class="container mt-5">
        <div class="card mb-4" id="myCollapseContainer">
            <div class="card-header d-flex justify-content-between align-items-center collapse-trigger">
                <h6 class="mb-0 fw-bold">折叠示例</h6>
                <i class="fas fa-chevron-down collapse-arrow"></i>
            </div>
            <div class="collapse-content" id="myCollapse">
                <div class="card-body">
                    <p>这是折叠内容区域</p>
                    <p>可以包含任何内容</p>
                </div>
            </div>
        </div>
        
        <div class="d-flex gap-2">
            <button id="toggleBtn" class="btn btn-primary">切换</button>
            <button id="expandBtn" class="btn btn-success">展开</button>
            <button id="collapseBtn" class="btn btn-danger">收起</button>
        </div>
    </div>
    
    <script src="bootstrap.bundle.min.js"></script>
    <script src="collapse-animated.js"></script>
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const collapse = new CollapseAnimated('#myCollapseContainer', {
                duration: 400,
                initialState: 'expanded',
                onExpand: () => console.log('已展开'),
                onCollapse: () => console.log('已收起')
            });
            
            document.getElementById('toggleBtn').addEventListener('click', () => collapse.toggle());
            document.getElementById('expandBtn').addEventListener('click', () => collapse.expand());
            document.getElementById('collapseBtn').addEventListener('click', () => collapse.collapse());
        });
    </script>
</body>
</html>
```

---

## 📄 许可证

MIT License

---

**最后更新**：2026-03-14  
**版本**：1.0.0  
**作者**：AI Assistant
