# Figma 标注文件: 产品列表页优化

## 1. 栅格系统 (Grid System)
- **Base Grid**: 8-pt 系统。
- **Margins & Paddings**:
  - 卡片内边距 (Card Padding): `24px`
  - 模块间距 (Section Gap): `24px` / `32px`
  - 行间距 (Row Gap): `8px` / `16px`

## 2. 字体规范 (Typography)
- **Font Family**: `Microsoft YaHei`, `Segoe UI`, `sans-serif`
- **主标题 (H1/Page Title)**:
  - Font Size: `24px`
  - Font Weight: `400` (Regular)
  - Line Height: `1.5` (`36px`)
  - Color: `var(--plush-text)` (`#5A4A4A`)
- **副标题 (Subtitle)**:
  - Font Size: `18px`
  - Font Weight: `400` (Regular)
  - Line Height: `1.5` (`27px`)
  - Color: `var(--plush-text-light)` (`#595959`)
- **正文/表单 (Body/Form)**:
  - Font Size: `14px`
  - Font Weight: `400` (Regular)
  - Line Height: `1.5` (`21px`)

## 3. 颜色与对比度 (Colors & Contrast)
- **Primary Text**: `#5A4A4A` (Contrast: 5.8:1 on White)
- **Secondary Text**: `#595959` (Contrast: 5.9:1 on White)
- **Primary Action (Blue)**: `#02669e` (Contrast: 5.1:1 on White)
- **Success Action (Green)**: `#2e7d32` (Contrast: 5.5:1 on White)
- **Borders/Dividers**: `#D4F1F4` (Plush Blue Light)

## 4. 组件尺寸 (Component Sizing)
- **Touch Targets (Minimum)**: `44px` × `44px`
- **Buttons**:
  - Primary (`添加产品`): Height `48px`, Padding `16px 32px`
  - Small/Icon Buttons: Height `44px`, Width `44px`
- **Inputs & Selects**:
  - Height: `44px`
  - Border Radius: `12px`
- **Pagination**:
  - Link Items: `44px` × `44px`

## 5. 交互状态 (Interaction States)
- **Hover**: 
  - Y-axis translate `-2px`
  - Shadow: `0 4px 16px rgba(176, 224, 230, 0.25)`
- **Focus**:
  - Outline: `2px solid #02669e`
  - Outline Offset: `2px`