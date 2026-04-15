## [LRN-20260320-001] CSS contain 属性导致点击事件路由异常

**Logged**: 2026-03-20T10:00:00Z
**Priority**: high
**Status**: completed
**Area**: frontend

### Summary
CSS `contain: layout style paint` 属性导致点击事件的目标元素变成了父元素而非实际点击的子元素，使用 `elementFromPoint` 和坐标判断可解决此问题。

### Details
**问题现象**：
- 产品上传管理的折叠面板点击标题栏无法展开
- Console 无错误日志
- 调试按钮调用 `collapseInstance.toggle()` 可以正常打开面板
- 点击位置确实在 `.collapse-trigger` 范围内
- 但 `elementFromPoint` 返回的是父元素 `#productUploadManager` 而不是子元素 `.collapse-trigger`

**根本原因**：
```css
.collapse-animated.reduce-reflow {
    contain: layout style paint;  /* 来自 collapse-animated.css */
}
```
当元素使用了 `contain: layout` 时，浏览器的点击事件路由机制会改变。点击 `.collapse-trigger` 子元素时，`e.target` 错误地返回了父元素。

**调试过程**：
1. 确认 JS 正常 - 调试按钮调用 `collapseInstance.toggle()` 可以打开面板
2. 确认元素存在 - `.collapse-trigger` DOM 元素存在，`pointer-events: auto` 正常
3. 确认点击位置正确 - 点击坐标确实在 `.collapse-trigger` 范围内
4. 使用 `elementFromPoint` 检测实际点击目标 - 发现返回的是父元素

**最终修复方案**：
```javascript
// 修复方案：document 级别点击拦截
document.addEventListener('click', function(e) {
    const trigger = document.querySelector('#productUploadManager > .collapse-trigger');
    if (!trigger) return;

    const triggerRect = trigger.getBoundingClientRect();
    const isInTrigger = (
        e.clientX >= triggerRect.left && e.clientX <= triggerRect.right &&
        e.clientY >= triggerRect.top && e.clientY <= triggerRect.bottom
    );

    if (isInTrigger && window.collapseInstance) {
        window.collapseInstance.toggle();
    }
});
```

### Suggested Action
当遇到以下情况时，考虑使用坐标判断替代事件委托：
1. CSS 使用了 `contain` 属性
2. `elementFromPoint` 返回的 `e.target` 与实际点击位置不符
3. 事件监听器存在但点击事件不触发

### Metadata
- Source: conversation
- Related Files: templates/product.html, static/collapse-animated.css
- Tags: css-contain, click-event, elementFromPoint, event-routing

---

## [LRN-20260320-002] 点击事件调试方法论

**Logged**: 2026-03-20T10:00:00Z
**Priority**: medium
**Status**: completed
**Area**: frontend

### Summary
系统化调试点击事件问题的方法：通过 `elementFromPoint` 验证实际点击目标，通过 `getComputedStyle` 检查 CSS 属性影响。

### Details
**调试步骤**：

1. **检查元素是否存在**：
```javascript
const trigger = document.querySelector('.collapse-trigger');
console.log('trigger:', trigger ? '存在' : '不存在');
```

2. **检查 CSS 属性**：
```javascript
const style = window.getComputedStyle(trigger);
console.log({
    pointerEvents: style.pointerEvents,
    display: style.display,
    visibility: style.visibility,
    zIndex: style.zIndex
});
```

3. **使用 elementFromPoint 验证点击目标**：
```javascript
const topEl = document.elementFromPoint(rect.left + rect.width/2, rect.top + rect.height/2);
console.log('该位置最顶层元素:', topEl?.tagName, topEl?.className);
```

4. **添加全局点击监听器**：
```javascript
document.addEventListener('click', function(e) {
    console.log('全局点击，目标:', e.target.tagName, e.target.className);
});
```

5. **坐标判断作为备选方案**：
```javascript
const rect = trigger.getBoundingClientRect();
const isInTrigger = (
    e.clientX >= rect.left && e.clientX <= rect.right &&
    e.clientY >= rect.top && e.clientY <= rect.bottom
);
```

### Metadata
- Source: conversation
- Tags: debugging, click-event, elementFromPoint, getComputedStyle

---

## [LRN-20260320-003] CollapseAnimated 组件集成注意事项

**Logged**: 2026-03-20T10:00:00Z
**Priority**: medium
**Status**: completed
**Area**: frontend

### Summary
使用 CollapseAnimated 组件时，需要注意 CSS contain 属性可能影响点击事件，以及将实例保存到 window 以便调试。

### Details
**问题场景**：
- CollapseAnimated 组件初始化正常，`.click()` 方法可以触发展开
- 但真实的鼠标点击无法触发
- 原因是 CSS contain 属性影响了事件路由

**解决方案**：
1. 将 CollapseAnimated 实例保存到 window：
```javascript
window.collapseInstance = new CollapseAnimated('#productUploadManager', {...});
```

2. 使用 document 级别点击拦截配合坐标判断

**最佳实践**：
- 初始化后保存实例到 window 方便调试
- 添加 `onExpand`、`onCollapse` 回调便于监控状态
- 考虑 CSS contain 对子元素事件的影响

### Metadata
- Source: conversation
- Related Files: templates/product.html, static/collapse-animated.js, static/collapse-animated.css
- Tags: CollapseAnimated, component-integration, debugging

---
