# [LRN-20260321-001] CSS伪元素覆盖导致点击事件失效

**Logged**: 2026-03-21
**Priority**: high
**Status**: resolved
**Area**: frontend

## Summary
CSS伪元素 `::before` 的 `z-index` 可能覆盖在真实元素上方，导致点击事件无法触发。

## Problem
订单列表的展开/收起功能点击无效，onclick 属性已正确设置，但点击时没有任何反应。

### 调试过程
1. 检查 onclick 属性 - 正确设置
2. 检查 cursor 样式 - 正确显示 pointer
3. 检查 pointer-events - 正确显示 auto
4. 添加手动事件绑定测试 - 仍然无效
5. 最终发现：`.card::before` 伪元素有 `z-index: 1`，覆盖在 `.card-header` 上

### 根本原因
```css
/* style.css 中的样式 */
.card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 1;  /* 这个伪元素覆盖在 header 上面！ */
}

.card-header {
    /* 没有 position 和 z-index，默认在伪元素下方 */
}
```

## Solution
给需要点击的元素添加更高的 z-index：

```css
.order-date-group .card-header {
    position: relative;
    z-index: 10;  /* 高于 .card::before 的 z-index: 1 */
}
```

## Key Takeaways
1. **伪元素会阻挡点击**：`::before` 和 `::after` 伪元素如果设置了 `z-index`，会覆盖在真实元素上方
2. **调试技巧**：当 onclick 不触发时，检查是否有伪元素覆盖
3. **z-index 层级**：需要点击的元素必须有足够高的 z-index

## Related Files
- `templates/order.html` - 订单页面
- `static/style.css` - 全局样式，`.card::before` 定义

## Tags
css, z-index, pseudo-element, click-event, debugging
