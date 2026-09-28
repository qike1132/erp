"""Tk 自绘控件与配色/字体助手(RoundedButton / StatusBadge)。

自 server_manager.py 原样迁出,未做重构。
"""
import math
import tkinter as tk

_font_cache = {}

def _font_exists(name):
    if name in _font_cache:
        return _font_cache[name]
    try:
        import tkinter.font as tkfont
        root = tk._default_root or tk.Tk()
        result = name in tkfont.families(root)
    except Exception:
        result = False
    _font_cache[name] = result
    return result

def _shift_color(hex_c, amount):
    """颜色偏移 - 模块级公共函数"""
    r = max(0, min(255, int(hex_c[1:3], 16) + amount))
    g = max(0, min(255, int(hex_c[3:5], 16) + amount))
    b = max(0, min(255, int(hex_c[5:7], 16) + amount))
    return f'#{r:02x}{g:02x}{b:02x}'

def _lerp_color(c1, c2, t):
    """颜色线性插值 - 模块级公共函数"""
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    return f'#{int(r1+(r2-r1)*t):02x}{int(g1+(g2-g1)*t):02x}{int(b1+(b2-b1)*t):02x}'

# 按钮视觉变体调色板 - 与 ServerManagerApp._PALETTE 严格对齐
# solid    状态：fill=fill（实色）/hover=fill_h（加深）/fg=#ffffff
# outlined 状态：fill=#ffffff /hover=tint_h（淡染色）/fg=fill / 边框=fill
# subtle   状态：fill=tint（极浅色）/hover=tint_h /fg=fill / 边框=subtle_border
_BUTTON_VARIANT_PALETTE = {
    'accent': {
        'fill': '#007aff', 'fill_h': '#0064d1', 'tint': '#e8f1ff', 'tint_h': '#d5e8ff',
        'fg': '#ffffff', 'subtle_border': '#c8dcfb',
        'transparent_fill': '#ffffff',
    },
    'success': {
        'fill': '#34c759', 'fill_h': '#2ba847', 'tint': '#e6f9ec', 'tint_h': '#d3f3dc',
        'fg': '#ffffff', 'subtle_border': '#bbe6c5',
        'transparent_fill': '#ffffff',
    },
    'danger': {
        'fill': '#ff3b30', 'fill_h': '#d92d22', 'tint': '#ffece9', 'tint_h': '#ffdad3',
        'fg': '#ffffff', 'subtle_border': '#f5b8b1',
        'transparent_fill': '#ffffff',
    },
    'neutral': {
        'fill': '#f2f2f7', 'fill_h': '#e5e5ea', 'tint': '#f2f2f7', 'tint_h': '#e5e5ea',
        'fg': '#1d1d1f', 'subtle_border': '#e5e5ea',
        'transparent_fill': '#ffffff',
    },
}

class RoundedButton(tk.Canvas):
    """基于 Canvas 的圆角按钮 — 三种视觉变体：solid / outlined / subtle。

    设计规格（统一）：
        高度    36px (padx=16, pady=6 + font linespace ≈ 36)；mini 26px (pady=2)
        圆角    10px (mini 8px)
        字号    9pt bold (mini 8pt)
        间距    水平 8px（在调用方以 padx=(8,0) 实施）
        Hover   180ms 平滑过渡到 +12 加深色（solid） / 主色 12% 透明染（outlined / subtle）
        Press   立即下沉 1px、背景再加深 6%
        Disabled 背景 #f2f2f7 / 文字 #aeaeb2 / 边框 #e5e5ea / cursor not-allowed
    """

    _DISABLED_BG = '#f2f2f7'
    _DISABLED_FG = '#aeaeb2'
    _DISABLED_BORDER = '#e5e5ea'

    def __init__(self, parent, text='', variant='solid', tone='accent',
                 command=None, font=('Microsoft YaHei UI', 9, 'bold'),
                 padx=16, pady=6, radius=10, state='normal', canvas_bg=None,
                 hover_fill=None, fg=None, fill=None, **kw):
        """variant: 'solid'(实色填充) / 'outlined'(边框+透明) / 'subtle'(淡色填充)
        tone:    'accent' / 'success' / 'danger' / 'neutral'
        其余旧参数（fill/hover_fill/fg）保留向后兼容。"""
        # 兼容旧 API：若调用方显式给了 fill 但未给 variant/toner，按旧模式当 solid 处理
        legacy = fill is not None and variant == 'solid' and tone == 'accent'
        if fill is not None and (fg is not None or hover_fill is not None):
            legacy = True

        palette = _BUTTON_VARIANT_PALETTE
        if legacy:
            # 老路子：fill/hover_fill 直接用调用方传入的；fg 走调用方
            cfg_fill = fill
            cfg_hover = hover_fill or _shift_color(fill, 18)
            cfg_fg = fg or '#ffffff'
            cfg_outline = ''
            cfg_outline_hover = ''
            cfg_outline_w = 0
            eff_variant = 'solid-legacy'
        else:
            tone_cfg = palette.get(tone, palette['accent'])
            if variant == 'solid':
                cfg_fill = tone_cfg['fill']
                cfg_hover = tone_cfg['fill_h']
                cfg_fg = tone_cfg['fg']
                cfg_outline = ''
                cfg_outline_hover = ''
                cfg_outline_w = 0
                eff_variant = 'solid'
            elif variant == 'outlined':
                cfg_fill = tone_cfg.get('transparent_fill', '#ffffff')
                cfg_hover = tone_cfg['tint_h']
                cfg_fg = tone_cfg['fill']
                cfg_outline = tone_cfg['fill']
                cfg_outline_hover = tone_cfg['fill_h']
                cfg_outline_w = 1
                eff_variant = 'outlined'
            elif variant == 'subtle':
                cfg_fill = tone_cfg['tint']
                cfg_hover = tone_cfg['tint_h']
                cfg_fg = tone_cfg['fill']
                cfg_outline = tone_cfg.get('subtle_border', _shift_color(tone_cfg['tint'], -12))
                cfg_outline_hover = tone_cfg['fill']
                cfg_outline_w = 1
                eff_variant = 'subtle'
            else:
                cfg_fill = tone_cfg['fill']; cfg_hover = tone_cfg['fill_h']; cfg_fg = tone_cfg['fg']
                cfg_outline = ''; cfg_outline_hover = ''; cfg_outline_w = 0
                eff_variant = 'solid'

        import tkinter.font as tkfont
        f = tkfont.Font(font=font)
        text_w = f.measure(text)
        # 最小宽度 80：避免窄按钮在小屏上挤成"重启"二字团
        w = max(80, text_w + padx * 2 + cfg_outline_w * 2)
        h = f.metrics('linespace') + pady * 2
        canvas_bg = canvas_bg or '#ffffff'
        cursor = 'hand2' if state == 'normal' else 'arrow'
        super().__init__(parent, width=w, height=h, highlightthickness=0, cursor=cursor, bg=canvas_bg, **kw)
        self._text = text
        self._fill, self._hover_fill, self._fg = cfg_fill, cfg_hover, cfg_fg
        self._outline = cfg_outline
        self._outline_hover = cfg_outline_hover
        self._outline_w = cfg_outline_w
        self._variant = eff_variant
        self._font, self._radius, self._command = font, radius, command
        self._state, self._hover, self._press = state, False, False
        self._anim_after_id = None
        self.bind('<Configure>', self._draw)
        self.bind('<Enter>', lambda e: self._hover_in())
        self.bind('<Leave>', lambda e: self._hover_out())
        self.bind('<ButtonPress-1>', lambda e: self._press_in())
        self.bind('<ButtonRelease-1>', lambda e: self._press_out())
        # 初始立即绘制（不依赖 <Configure>），避免按钮首次显示为空白、鼠标移上才出现
        self._draw()

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2, x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _draw(self, _=None):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        # widget 尚未映射时 winfo_width/height 会返回 1，回退到显式请求的尺寸
        if w < 4:
            w = self.winfo_reqwidth()
        if h < 4:
            h = self.winfo_reqheight()
        if w < 4 or h < 4:
            return
        r = min(self._radius, w // 2, h // 2)
        if self._state == 'disabled':
            bg, fg = self._DISABLED_BG, self._DISABLED_FG
            outline, outline_w = self._DISABLED_BORDER, 1
        else:
            if self._press:
                bg = _lerp_color(self._fill, self._hover_fill, 0.7)
                outline = _lerp_color(self._outline, self._outline_hover, 0.7) if self._outline else ''
                fg = self._fg
            elif self._hover:
                bg = self._hover_fill
                outline = self._outline_hover if self._outline else ''
                fg = self._fg
            else:
                bg = self._fill
                outline = self._outline
                fg = self._fg
            outline_w = self._outline_w
        offset = 1 if self._press else 0
        if outline_w and outline:
            # 双层圆角矩形模拟边框：外层用 outline 色实心填圆角，内层缩小 outline_w 后填 bg 色
            self._round_rect(offset, offset, w - offset, h - offset, r, fill=outline, outline='')
            self._round_rect(offset + outline_w, offset + outline_w,
                             w - offset - outline_w, h - offset - outline_w,
                             max(0, r - outline_w), fill=bg, outline='')
        else:
            self._round_rect(offset, offset, w - offset, h - offset, r, fill=bg, outline='')
        self.create_text(w // 2, h // 2, text=self._text, fill=fg, font=self._font)

    def _animate_hover(self, target_hover):
        if self._state == 'disabled':
            self._draw()
            return
        if self._anim_after_id:
            self.after_cancel(self._anim_after_id)
            self._anim_after_id = None
        start_bg = self._fill if not target_hover else self._hover_fill
        end_bg = self._hover_fill if target_hover else self._fill
        start_outline = self._outline if not target_hover else self._outline_hover
        end_outline = self._outline_hover if target_hover else self._outline
        step_idx = [0]
        steps = 4
        def step():
            step_idx[0] += 1
            t = step_idx[0] / steps
            if t >= 1.0:
                self._hover = target_hover
                self._draw()
                return
            self.delete('all')
            w, h = self.winfo_width(), self.winfo_height()
            if w < 4 or h < 4:
                return
            r = min(self._radius, w // 2, h // 2)
            if self._outline_w and self._outline:
                self._round_rect(0, 0, w, h, r, fill=_lerp_color(start_outline, end_outline, t), outline='')
                bg = _lerp_color(start_bg, end_bg, t)
                self._round_rect(self._outline_w, self._outline_w, w - self._outline_w, h - self._outline_w,
                                 max(0, r - self._outline_w), fill=bg, outline='')
            else:
                self._round_rect(0, 0, w, h, r, fill=_lerp_color(start_bg, end_bg, t), outline='')
            self.create_text(w // 2, h // 2, text=self._text, fill=self._fg, font=self._font)
            self._anim_after_id = self.after(45, step)
        step()

    def _hover_in(self):
        if self._state != 'disabled':
            self._animate_hover(True)

    def _hover_out(self):
        if self._state != 'disabled':
            self._animate_hover(False)

    def _press_in(self):
        if self._state != 'disabled':
            self._press = True
            self._draw()

    def _press_out(self):
        was_pressed = self._press
        self._press = False
        self._draw()
        if was_pressed and self._state == 'normal' and self._command:
            self._command()

    def config(self, **kw):
        if 'state' in kw:
            self._state = kw.pop('state')
            kw['cursor'] = 'arrow' if self._state == 'disabled' else 'hand2'
        if 'text' in kw:
            self._text = kw.pop('text')
        super().config(**kw)
        self._draw()

# 状态徽章：统一状态枚举 → 文案/颜色/点样式/动画（大厂 Status Tag 设计规范）
_STATUS_META = {
    'running':       {'text': '运行中', 'color': 'success',     'tint': 'success_tint', 'dot': 'dot',   'anim': 'breath'},
    'stopped':       {'text': '已停止', 'color': 'text_dim',    'tint': 'bg_input',     'dot': 'ring',  'anim': None},
    'error':         {'text': '异常',   'color': 'danger',      'tint': 'danger_tint',  'dot': 'cross', 'anim': 'pulse'},
    'restarting':    {'text': '重启中', 'color': 'warning',     'tint': 'warning_tint', 'dot': 'dot',   'anim': 'blink'},
    'deploying':     {'text': '部署中', 'color': 'accent',      'tint': 'accent_tint',  'dot': 'arc',   'anim': 'spin'},
    'not_installed': {'text': '未安装', 'color': 'text_dim',    'tint': 'bg_input',     'dot': 'ring',  'anim': None},
    'unknown':       {'text': '状态未知', 'color': 'text_dim',  'tint': 'bg_input',     'dot': 'ring',  'anim': None},
}

_STATUS_SIZE = {
    'lg': {'padx': 10, 'pady': 4, 'dot': 8, 'gap': 6, 'font': ('Microsoft YaHei UI', 9, 'bold'), 'radius': 10},
    'md': {'padx': 8,  'pady': 3, 'dot': 7, 'gap': 5, 'font': ('Microsoft YaHei UI', 9, 'bold'), 'radius': 9},
    'sm': {'padx': 6,  'pady': 2, 'dot': 6, 'gap': 4, 'font': ('Microsoft YaHei UI', 8),         'radius': 7},
}

class StatusBadge(tk.Canvas):
    """圆角胶囊状态徽章：状态点 + 文字 + 语义色容器（大厂 Status Tag 风格）。

    与旧版"裸圆点 + 裸文字"的区别：统一状态枚举、彩色胶囊容器、
    四种点样式（实心/空心/叉/旋转弧）、四种动画（呼吸/闪烁/脉冲/旋转）。
    用于三种场景：状态栏(lg) / 卡片详情(md) / 监控面板组件(sm)。
    """

    def __init__(self, parent, state='stopped', text=None, size='md', palette=None, canvas_bg=None):
        self._palette = palette or {}
        self._size = size
        self._spec = _STATUS_SIZE[size]
        self._state = state
        self._custom_text = text
        self._anim_after_id = None
        self._phase = 0
        self._meta = _STATUS_META.get(state, _STATUS_META['stopped'])
        self._anim_kind = self._meta['anim']
        import tkinter.font as tkfont
        self._font_obj = tkfont.Font(font=self._spec['font'])
        w = self._calc_width()
        h = self._font_obj.metrics('linespace') + self._spec['pady'] * 2
        super().__init__(parent, width=w, height=h, highlightthickness=0, bg=canvas_bg or '#ffffff')
        self._draw()
        if self._anim_kind:
            self._tick()

    def _text(self):
        return self._custom_text if self._custom_text is not None else self._meta['text']

    def _calc_width(self):
        text_w = self._font_obj.measure(self._text())
        return self._spec['padx'] * 2 + self._spec['dot'] + self._spec['gap'] + text_w

    def set_state(self, state, text=None, color_key=None, tint_key=None):
        prev_state = self._state
        self._state = state
        if text is not None:
            self._custom_text = text
        elif state != prev_state:
            self._custom_text = None
        base = _STATUS_META.get(state, _STATUS_META['stopped'])
        self._meta = dict(base)
        if color_key is not None:
            self._meta['color'] = color_key
        if tint_key is not None:
            self._meta['tint'] = tint_key
        new_anim = self._meta['anim']
        if new_anim != self._anim_kind:
            self._anim_kind = new_anim
            if self._anim_after_id:
                self.after_cancel(self._anim_after_id)
                self._anim_after_id = None
            self._phase = 0
            if self._anim_kind:
                self._tick()
        self.configure(width=self._calc_width())
        self._draw()

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2, x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _colors(self):
        color = self._palette.get(self._meta['color'], '#8e8e93')
        tint = self._palette.get(self._meta['tint'], '#f2f2f7')
        if self._anim_kind == 'blink' and (self._phase // 90) % 2 == 0:
            color = tint
        return color, tint

    def _draw(self):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            w = self.winfo_reqwidth()
        if h < 4:
            h = self.winfo_reqheight()
        if w < 4 or h < 4:
            return
        color, tint = self._colors()
        # 胶囊容器（圆角 + 同色描边）
        self._round_rect(0, 0, w, h, self._spec['radius'], fill=tint, outline=color, width=1)
        # 状态点
        cy = h // 2
        dx = self._spec['padx'] + self._spec['dot'] // 2
        self._draw_dot(dx, cy, self._spec['dot'], color, self._meta['dot'])
        # 文字
        tx = self._spec['padx'] + self._spec['dot'] + self._spec['gap']
        self.create_text(tx, cy, text=self._text(), fill=color, font=self._spec['font'], anchor='w')

    def _draw_dot(self, cx, cy, d, color, style):
        r = max(2, d // 2)
        phase = self._phase
        if style == 'ring':
            self.create_oval(cx-r, cy-r, cx+r, cy+r, outline=color, width=1)
        elif style == 'cross':
            self.create_oval(cx-r, cy-r, cx+r, cy+r, fill=color, outline='')
            k = max(1, r - 1)
            self.create_line(cx-k, cy-k, cx+k, cy+k, fill='#ffffff', width=1)
            self.create_line(cx+k, cy-k, cx-k, cy+k, fill='#ffffff', width=1)
        elif style == 'arc':
            self.create_arc(cx-r, cy-r, cx+r, cy+r, start=phase % 360, extent=270, style='arc', outline=color, width=2)
        else:
            if self._anim_kind == 'breath':
                glow = int((math.sin(phase / 360.0 * 2 * math.pi) * 0.5 + 0.5) * (r // 2))
                if glow:
                    self.create_oval(cx-r-glow, cy-r-glow, cx+r+glow, cy+r+glow, fill=_shift_color(color, 40), outline='')
            elif self._anim_kind == 'pulse':
                ring_r = (phase % 60) / 60.0 * (r + 3)
                if ring_r > 0.5:
                    self.create_oval(cx-ring_r, cy-ring_r, cx+ring_r, cy+ring_r, outline=color, width=1)
            self.create_oval(cx-r, cy-r, cx+r, cy+r, fill=color, outline='')

    def _tick(self):
        self._phase = (self._phase + 6) % 360
        self._draw()
        delay = {'breath': 200, 'blink': 120, 'pulse': 150, 'spin': 80}.get(self._anim_kind, 200)
        self._anim_after_id = self.after(delay, self._tick)

    def stop_animation(self):
        if self._anim_after_id:
            self.after_cancel(self._anim_after_id)
            self._anim_after_id = None
        self._anim_kind = None
        self._phase = 0
        self._draw()
