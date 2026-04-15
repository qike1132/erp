---
name: "erp-ui-design"
description: "Documents ERP system UI design specifications including color scheme, typography, components, and interaction patterns. Invoke when creating or modifying UI elements."
---

# ERP System UI Design Specification

## Overview

This document defines the comprehensive UI design specifications for the ERP system. The design follows a "Plush Cute" aesthetic - a soft, friendly, and modern interface style that emphasizes usability while maintaining visual appeal.

## Design Philosophy

- **Tone**: Friendly, modern, professional yet approachable
- **Aesthetic**: Soft, plush, clean with subtle shadows and rounded corners
- **User Experience**: Intuitive, responsive, accessible

---

## 1. Color Scheme

### Primary Palette

| Color Name | Hex Code | Usage |
|------------|----------|-------|
| Plush Blue | `#B0E0E6` | Primary accent, borders |
| Plush Blue Light | `#D4F1F4` | Hover states, secondary backgrounds |
| Plush Blue Deep | `#87CEEB` | Active states, emphasis |
| Plush White | `#FFFFFF` | Main background |
| Plush Cream | `#F8F9FA` | Alternative backgrounds |

### Text Colors

| Color Name | Hex Code | Usage |
|------------|----------|-------|
| Plush Text | `#5A4A4A` | Primary text |
| Plush Text Light | `#8B7B7B` | Secondary text, captions |

### Shadow Colors

| Name | Value | Usage |
|------|-------|-------|
| `--plush-shadow-soft` | `rgba(176, 224, 230, 0.25)` | Subtle shadows |
| `--plush-shadow-medium` | `rgba(135, 206, 235, 0.35)` | Stronger shadows |

### Status Badge Colors

| Status | Class | Color |
|--------|-------|-------|
| Success/备货 | `bg-success` | `#198754` |
| Danger/出货 | `bg-danger` | `#DC3545` |
| Primary/订单 | `bg-primary` | `#0D6EFD` |
| Warning/订单抵扣 | `bg-warning` | `#FFC107` (text-dark) |
| Info/初始库存 | `bg-info` | `#0DCAF0` |
| Secondary | `bg-secondary` | `#6C757D` |

---

## 2. Typography

### Font Family

```css
font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
```

### Font Sizes

| Element | Size | Weight |
|---------|------|--------|
| Page Title (h2) | 28px | 600 |
| Card Title (h5) | 20px | 600 |
| Body Text | 14px | 400 |
| Small Text | 12px | 400 |
| Button Text | 14px | 600 |
| Badge Text | 12px | 400 |

---

## 3. Border Radius

### Component-Specific Radii

| Component | Variable | Value |
|-----------|----------|-------|
| Card | `--radius-card` | 24px |
| Button | `--radius-button` | 14px |
| Input | `--radius-input` | 12px |
| Extra Large | `--radius-xl` | 28px |
| Large | `--radius-lg` | 20px |
| Medium | `--radius-md` | 14px |
| Small | `--radius-sm` | 10px |

---

## 4. Component Styles

### 4.1 Cards

```html
<div class="card mt-3">
    <div class="card-header">Title</div>
    <div class="card-body">Content</div>
</div>
```

**Specifications:**
- Border radius: 24px
- Box shadow: `0 4px 20px var(--plush-shadow-soft)`
- Header: Light background, padding 16px
- Body: White background, padding 20px

### 4.2 Buttons

**Primary Button:**
```html
<button class="btn btn-primary">Text</button>
```

**Secondary Button:**
```html
<button class="btn btn-secondary">Text</button>
```

**Outline Button:**
```html
<button class="btn btn-outline-primary">Text</button>
```

**Specifications:**
- Border radius: 14px
- Padding: 12px 24px
- Min height: 44px
- Transition: `all 0.4s cubic-bezier(0.4, 0, 0.2, 1)`
- Box shadow: Subtle with inset highlight

### 4.3 Form Inputs

```html
<input type="text" class="form-control" id="field" name="field">
<select class="form-select" id="field" name="field">
<textarea class="form-control" id="field" name="field" rows="3">
```

**Specifications:**
- Border radius: 12px
- Border: 1px solid `#D4F1F4`
- Focus: Blue border with subtle shadow
- Padding: 10px 14px

### 4.4 Tables

```html
<table class="table table-striped">
    <thead>
        <tr><th>Header</th></tr>
    </thead>
    <tbody>
        <tr><td>Data</td></tr>
    </tbody>
</table>
```

**Specifications:**
- Striped rows with alternating colors
- Hover effect on rows
- Border: 1px solid `#dee2e6`
- Cell padding: 12px

### 4.5 Badges

```html
<span class="badge bg-primary">Text</span>
<span class="badge bg-success">Text</span>
<span class="badge bg-danger">Text</span>
```

**Specifications:**
- Border radius: 6px
- Padding: 4px 10px
- Font size: 12px

---

## 5. Layout Specifications

### 5.1 Grid System

- Use Bootstrap 5 grid: `.row` with `.col-*` classes
- Standard breakpoints: col-md-3, col-md-4, col-md-6, col-md-8, col-md-12
- Gap between columns: `g-3` or `gap-2`

### 5.2 Spacing Scale

| Name | Value | Usage |
|------|-------|-------|
| mt-3 | 16px | Card top margin |
| mb-2 | 8px | Element bottom margin |
| mb-3 | 16px | Section bottom margin |
| mb-4 | 24px | Large section gap |
| p-3 | 16px | Padding |
| py-4 | 32px | Vertical padding |

### 5.3 Card Layout (Two-Column)

```html
<div class="row">
    <div class="col-lg-6">
        <div class="card mt-3">Form Section</div>
    </div>
    <div class="col-lg-6">
        <div class="card mt-3">List Section</div>
    </div>
</div>
```

---

## 6. Interaction Patterns

### 6.1 Card Hover Effect

**Required Parameters:**
```css
.card {
    transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.card:hover {
    transform: translateY(-1px) scale(1.01);
    box-shadow: 0 8px 25px var(--plush-shadow-medium);
}
```

- **Displacement**: 1px upward
- **Scale**: 1.01x
- **Transition duration**: 0.4 seconds
- **Easing**: cubic-bezier(0.4, 0, 0.2, 1)
- **No rotation**

### 6.2 Button Hover

```css
.btn:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px var(--plush-shadow-medium);
}
```

### 6.3 Form Focus

```css
.form-control:focus,
.form-select:focus {
    border-color: var(--plush-blue-deep);
    box-shadow: 0 0 0 0.2rem rgba(135, 206, 235, 0.25);
}
```

### 6.4 Collapse Animation

For collapsible panels like search forms:

```html
<div class="collapse show" id="panelId">
    <!-- Content -->
</div>
```

Use Bootstrap 5 collapse component with custom toggle button.

---

## 7. Page Structure Templates

### 7.1 Standard Module Page

```html
{% extends 'base.html' %}

{% block content %}
    <h2>模块标题</h2>
    
    <!-- Two-column layout -->
    <div class="row">
        <div class="col-lg-6">
            <div class="card mt-3">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <span>表单标题</span>
                    <span class="badge bg-info" id="countBadge">数量</span>
                </div>
                <div class="card-body">
                    <form id="form">
                        <div class="row mb-3">
                            <div class="col-md-6">
                                <label for="field1" class="form-label">字段1</label>
                                <input type="text" class="form-control" id="field1">
                            </div>
                            <div class="col-md-6">
                                <label for="field2" class="form-label">字段2</label>
                                <input type="text" class="form-control" id="field2">
                            </div>
                        </div>
                        <div class="d-flex gap-2">
                            <button type="button" class="btn btn-primary">提交</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
        
        <div class="col-lg-6">
            <div class="card mt-3">
                <div class="card-header">
                    <span>列表标题</span>
                </div>
                <div class="card-body">
                    <!-- List content -->
                </div>
            </div>
        </div>
    </div>
    
    <!-- Full-width table -->
    <div class="card mt-4">
        <div class="card-header">记录列表</div>
        <div class="card-body">
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>列1</th>
                        <th>列2</th>
                        <th>列3</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
                    {% for item in items %}
                    <tr>
                        <td>{{ item.field1 }}</td>
                        <td>{{ item.field2 }}</td>
                        <td>{{ item.field3 }}</td>
                        <td>
                            <a href="{{ url_for('edit', id=item.id) }}" class="btn btn-sm btn-warning">编辑</a>
                            <a href="{{ url_for('delete', id=item.id) }}" class="btn btn-sm btn-danger" onclick="return confirm('确定删除?')">删除</a>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
{% endblock %}
```

### 7.2 Search/Filter Panel

```html
<div class="card mt-3">
    <div class="card-header">
        <div class="d-flex justify-content-between align-items-center">
            <span>查询条件</span>
            <button class="btn btn-sm btn-outline-secondary" type="button" data-bs-toggle="collapse" data-bs-target="#searchPanel">
                <i class="fas fa-chevron-down"></i>
            </button>
        </div>
    </div>
    <div class="collapse show" id="searchPanel">
        <div class="card-body">
            <form method="GET" action="{{ url_for('route') }}">
                <div class="row g-3">
                    <div class="col-md-3">
                        <label class="form-label">字段1</label>
                        <select class="form-select" name="field1">
                            <option value="">全部</option>
                        </select>
                    </div>
                    <div class="col-md-3">
                        <label class="form-label">字段2</label>
                        <input type="text" class="form-control" name="field2">
                    </div>
                    <div class="col-md-2">
                        <label class="form-label">开始日期</label>
                        <input type="date" class="form-control" name="start_date">
                    </div>
                    <div class="col-md-2">
                        <label class="form-label">结束日期</label>
                        <input type="date" class="form-control" name="end_date">
                    </div>
                    <div class="col-md-2 d-flex align-items-end">
                        <div class="d-flex gap-2 w-100">
                            <button type="submit" class="btn btn-primary flex-grow-1">
                                <i class="fas fa-search"></i> 查询
                            </button>
                            <a href="{{ url_for('route') }}" class="btn btn-outline-secondary">
                                <i class="fas fa-redo"></i>
                            </a>
                        </div>
                    </div>
                </div>
            </form>
        </div>
    </div>
</div>
```

### 7.3 Staged Items List (Batch Processing)

```html
<div class="card mt-3">
    <div class="card-header">
        <div class="d-flex justify-content-between align-items-center">
            <span>暂存列表</span>
            <span class="badge bg-primary">共 {{ items|length }} 个</span>
        </div>
    </div>
    <div class="card-body">
        <div id="stagedList" style="max-height: 400px; overflow-y: auto;">
            {% for item in items %}
            <div class="card mb-2" style="border: 2px solid var(--plush-blue-light);">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <h6 class="mb-1">{{ item.name }}</h6>
                            <p class="mb-0 small text-muted">
                                <span class="badge bg-info">数量：{{ item.quantity }}</span>
                            </p>
                        </div>
                        <div class="d-flex gap-1">
                            <button class="btn btn-sm btn-outline-warning" onclick="editItem({{ loop.index0 }})">
                                <i class="fas fa-edit"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-danger" onclick="deleteItem({{ loop.index0 }})">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
            {% else %}
            <div class="text-center text-muted py-4">
                <i class="fas fa-inbox fa-3x mb-3" style="opacity: 0.3;"></i>
                <p>暂无暂存</p>
            </div>
            {% endfor %}
        </div>
    </div>
</div>
```

---

## 8. Icons

Use Font Awesome 5 for icons:

```html
<i class="fas fa-plus-circle"></i>
<i class="fas fa-edit"></i>
<i class="fas fa-trash"></i>
<i class="fas fa-search"></i>
<i class="fas fa-filter"></i>
<i class="fas fa-history"></i>
<i class="fas fa-box"></i>
<i class="fas fa-shipping-fast"></i>
```

---

## 9. Implementation Checklist

When creating a new module or modifying UI:

- [ ] Use CSS variables for all colors
- [ ] Apply consistent border radius (24px for cards, 14px for buttons)
- [ ] Include hover animations with specified parameters
- [ ] Use Bootstrap 5 grid system
- [ ] Apply proper spacing using utility classes
- [ ] Include proper form validation feedback
- [ ] Use consistent badge styling for status indicators
- [ ] Implement responsive design with Bootstrap breakpoints
- [ ] Add proper accessibility attributes (aria-labels, etc.)

---

## 10. File Locations

| File | Purpose |
|------|---------|
| `static/style.css` | Global styles and CSS variables |
| `templates/base.html` | Base template with layout |
| `templates/*.html` | Module-specific templates |

---

## References

- Bootstrap 5: https://getbootstrap.com/docs/5.3/
- Font Awesome 5: https://fontawesome.com/v5/icons
- Google Fonts: Microsoft YaHei (for Chinese support)
