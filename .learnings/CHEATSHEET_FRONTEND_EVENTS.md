# 前端事件处理 - 快速参考卡片

## 🚀 标准模板（复制粘贴用）

```javascript
document.addEventListener('DOMContentLoaded', function() {
    console.log('[模块名] 开始初始化...');
    
    // 1. 获取元素
    const element = document.getElementById('element-id');
    
    // 2. 检查存在性
    if (!element) {
        console.error('[模块名] 元素不存在');
        return;
    }
    
    // 3. 绑定事件
    element.addEventListener('click', (e) => {
        e.stopPropagation(); // 需要时添加
        e.preventDefault();  // 需要时添加
        console.log('[模块名] 事件触发');
        // 处理逻辑...
    });
    
    console.log('[模块名] 初始化完成！');
});
```

---

## ✅ 检查清单

### 编写事件处理代码时

- [ ] 使用 `DOMContentLoaded` 包裹
- [ ] 检查元素是否存在
- [ ] 添加 `console.log` 调试日志
- [ ] 添加 `console.error` 错误处理
- [ ] 需要时调用 `stopPropagation()`
- [ ] 需要时调用 `preventDefault()`

### 测试时

- [ ] 点击交互正常
- [ ] 拖拽交互正常（如有）
- [ ] 控制台无红色错误
- [ ] 显示"初始化完成"日志
- [ ] 功能按预期工作

---

## ⚠️ 常见陷阱

### 陷阱 1：元素为 null

```javascript
// ❌ 错误
const el = document.getElementById('myEl');
el.addEventListener('click', ...); // 报错！

// ✅ 正确
const el = document.getElementById('myEl');
if (!el) {
    console.error('元素不存在');
    return;
}
el.addEventListener('click', ...);
```

---

### 陷阱 2：事件冒泡

```javascript
// ❌ 错误 - 会触发父元素事件
child.addEventListener('click', (e) => {
    doSomething();
});

// ✅ 正确 - 阻止冒泡
child.addEventListener('click', (e) => {
    e.stopPropagation();
    doSomething();
});
```

---

### 陷阱 3：时序问题

```javascript
// ❌ 错误 - 立即执行
const el = document.getElementById('myEl');

// ✅ 正确 - 等待 DOM 加载
document.addEventListener('DOMContentLoaded', function() {
    const el = document.getElementById('myEl');
});
```

---

## 🎯 决策流程

```
需要操作 DOM？
│
├─ 是 → 使用 DOMContentLoaded 包裹
│
├─ 获取元素
│
├─ 检查是否存在？
│  ├─ 否 → console.error + return
│  └─ 是 → 继续
│
├─ 需要阻止默认行为？
│  ├─ 是 → e.preventDefault()
│  └─ 否 → 跳过
│
├─ 需要阻止事件冒泡？
│  ├─ 是（父元素有事件）
│  │  └─ e.stopPropagation()
│  └─ 否 → 跳过
│
└─ 执行处理逻辑
```

---

## 📝 调试命令（控制台用）

```javascript
// 检查元素
console.log(document.getElementById('myEl'));

// 检查事件监听器
console.log(element.onclick !== null);

// 手动触发点击
document.getElementById('myEl').click();

// 查看控制台日志
// 应该看到：
// [模块名] 开始初始化...
// [模块名] 元素已就绪
// [模块名] 初始化完成！
```

---

## 🔑 关键 API

| API | 作用 | 何时使用 |
|-----|------|---------|
| `DOMContentLoaded` | 等待 DOM 加载 | 所有 DOM 操作前 |
| `getElementById` | 获取元素 | 需要操作元素时 |
| `addEventListener` | 绑定事件 | 需要响应交互时 |
| `stopPropagation` | 阻止冒泡 | 父元素有事件时 |
| `preventDefault` | 阻止默认行为 | 表单、链接、拖拽时 |

---

## 📖 完整文档

- `FRONTEND_EVENT_HANDLING_BEST_PRACTICES.md` - 完整最佳实践
- `LRN-20260314-001-batch-upload-fix.md` - 问题学习记录
- `QUICK_VERIFY.md` - 快速验证指南

---

**打印提示**：将此卡片打印出来，放在办公桌旁随时参考！

**最后更新**：2026-03-14
