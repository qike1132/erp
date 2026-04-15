/**
 * 高质量折叠UI动画控制器
 * 
 * 特点：
 * - 使用CSS transform和opacity实现平滑动画，避免布局抖动
 * - 可配置动画参数
 * - 性能优化，使用requestAnimationFrame
 * - 事件驱动架构
 * - 无障碍支持
 * 
 * 浏览器支持：
 * - Chrome 74+
 * - Firefox 69+
 * - Safari 13.1+
 * - Edge 79+
 */

class CollapseAnimated {
    /**
     * 默认配置
     */
    static defaultOptions = {
        duration: 400,           // 动画持续时间 (ms)
        easing: 'cubic-bezier(0.4, 0, 0.2, 1)',  // 展开easing
        easingOut: 'cubic-bezier(0, 0, 0.2, 1)', // 收起easing
        arrowDuration: 300,      // 箭头动画持续时间 (ms)
        arrowEasing: 'ease-in-out', // 箭头easing
        initialState: 'expanded', // 初始状态: 'expanded' 或 'collapsed'
        triggerSelector: '.collapse-trigger', // 触发元素选择器
        contentSelector: '.collapse-content', // 内容区域选择器
        arrowSelector: '.collapse-arrow', // 箭头元素选择器
        onExpand: null,           // 展开回调
        onCollapse: null,         // 收起回调
        onToggle: null,           // 切换回调
        onAnimating: null,        // 动画中回调
        useHardwareAcceleration: true, // 使用硬件加速
        reduceReflow: true,       // 减少重绘
        accessibility: true       // 无障碍支持
    };

    /**
     * 构造函数
     * @param {HTMLElement|string} element - 折叠容器元素或选择器
     * @param {Object} options - 配置选项
     */
    constructor(element, options = {}) {
        this.element = typeof element === 'string' 
            ? document.querySelector(element) 
            : element;

        if (!this.element) {
            console.error('CollapseAnimated: 元素未找到');
            return;
        }

        this.options = { ...CollapseAnimated.defaultOptions, ...options };
        this.isAnimating = false;
        this.animationFrameId = null;
        this.state = this.options.initialState;

        this.init();
    }

    /**
     * 初始化
     */
    init() {
        this.setupDOM();
        this.setupEventListeners();
        this.applyInitialState();
        this.applyPerformanceOptimizations();
        this.setupAccessibility();
    }

    /**
     * 设置DOM结构
     */
    setupDOM() {
        // 添加基础类
        this.element.classList.add('collapse-animated');
        
        // 找到内容区域
        this.content = this.element.querySelector(this.options.contentSelector);
        if (!this.content) {
            console.warn('CollapseAnimated: 内容区域未找到，自动创建');
            this.content = document.createElement('div');
            this.content.className = 'collapse-content';
            
            while (this.element.firstChild) {
                this.content.appendChild(this.element.firstChild);
            }
            this.element.appendChild(this.content);
        }

        // 创建内部包装器（用于transform动画）
        this.inner = document.createElement('div');
        this.inner.className = 'collapse-inner';
        
        while (this.content.firstChild) {
            this.inner.appendChild(this.content.firstChild);
        }
        this.content.appendChild(this.inner);

        // 找到触发元素
        this.trigger = this.element.querySelector(this.options.triggerSelector);
        if (!this.trigger) {
            console.warn('CollapseAnimated: 触发元素未找到');
        }

        // 找到箭头元素
        this.arrow = this.element.querySelector(this.options.arrowSelector);
        if (!this.arrow && this.trigger) {
            console.warn('CollapseAnimated: 箭头元素未找到，自动创建');
            this.arrow = document.createElement('i');
            this.arrow.className = 'collapse-arrow fas fa-chevron-down';
            this.trigger.appendChild(this.arrow);
        }

        // 应用CSS变量
        this.applyCSSVariables();
    }

    /**
     * 应用CSS变量
     */
    applyCSSVariables() {
        this.element.style.setProperty('--collapse-duration', `${this.options.duration}ms`);
        this.element.style.setProperty('--collapse-easing', this.options.easing);
        this.element.style.setProperty('--collapse-easing-out', this.options.easingOut);
        this.element.style.setProperty('--collapse-arrow-duration', `${this.options.arrowDuration}ms`);
        this.element.style.setProperty('--collapse-arrow-easing', this.options.arrowEasing);
    }

    /**
     * 设置事件监听器
     */
    setupEventListeners() {
        if (this.trigger) {
            this.trigger.addEventListener('click', (e) => this.handleTriggerClick(e));
            this.trigger.addEventListener('keydown', (e) => this.handleKeyDown(e));
        }
    }

    /**
     * 处理触发点击
     */
    handleTriggerClick(e) {
        e.preventDefault();
        this.toggle();
    }

    /**
     * 处理键盘事件
     */
    handleKeyDown(e) {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            this.toggle();
        }
    }

    /**
     * 应用初始状态
     */
    applyInitialState() {
        if (this.state === 'collapsed') {
            this.element.classList.add('collapsed');
            this.element.classList.remove('expanded');
        } else {
            this.element.classList.add('expanded');
            this.element.classList.remove('collapsed');
        }
    }

    /**
     * 应用性能优化
     */
    applyPerformanceOptimizations() {
        if (this.options.useHardwareAcceleration) {
            this.element.classList.add('hardware-accelerated');
        }
        if (this.options.reduceReflow) {
            this.element.classList.add('reduce-reflow');
        }
    }

    /**
     * 设置无障碍支持
     */
    setupAccessibility() {
        if (!this.options.accessibility) return;

        // 设置ARIA属性
        if (this.trigger) {
            this.trigger.setAttribute('role', 'button');
            this.trigger.setAttribute('tabindex', '0');
            this.trigger.setAttribute('aria-expanded', this.state === 'expanded');
            this.trigger.setAttribute('aria-controls', this.content.id || 'collapse-content');
        }

        if (this.content) {
            this.content.id = this.content.id || 'collapse-content';
            this.content.setAttribute('aria-hidden', this.state === 'collapsed');
        }
    }

    /**
     * 切换展开/收起状态
     */
    toggle() {
        if (this.isAnimating) return;

        if (this.state === 'expanded') {
            this.collapse();
        } else {
            this.expand();
        }
    }

    /**
     * 展开
     */
    expand() {
        if (this.isAnimating || this.state === 'expanded') return;

        this.isAnimating = true;
        this.triggerAnimation('expand');
    }

    /**
     * 收起
     */
    collapse() {
        if (this.isAnimating || this.state === 'collapsed') return;

        this.isAnimating = true;
        this.triggerAnimation('collapse');
    }

    /**
     * 触发动画
     */
    triggerAnimation(direction) {
        const isExpanding = direction === 'expand';

        // 回调：动画开始
        if (this.options.onAnimating) {
            this.options.onAnimating(isExpanding);
        }

        // 添加动画类
        this.element.classList.add('animating');

        // 使用requestAnimationFrame确保动画平滑
        this.animationFrameId = requestAnimationFrame(() => {
            if (isExpanding) {
                // 更新状态类
                this.element.classList.remove('collapsed');
                this.element.classList.add('expanded');
                
                // 回调：展开
                if (this.options.onExpand) {
                    this.options.onExpand();
                }
                if (this.options.onToggle) {
                    this.options.onToggle(true);
                }
                
                // 更新ARIA
                this.updateAccessibility(true);
            } else {
                // 更新状态类
                this.element.classList.remove('expanded');
                this.element.classList.add('collapsed');
                
                // 回调：收起
                if (this.options.onCollapse) {
                    this.options.onCollapse();
                }
                if (this.options.onToggle) {
                    this.options.onToggle(false);
                }
                
                // 更新ARIA
                this.updateAccessibility(false);
            }

            // 更新内部状态
            this.state = isExpanding ? 'expanded' : 'collapsed';
        });

        // 监听动画结束
        const animationDuration = this.options.duration + 50; // 增加50ms缓冲
        setTimeout(() => {
            this.finishAnimation();
        }, animationDuration);
    }

    /**
     * 完成动画
     */
    finishAnimation() {
        this.isAnimating = false;
        this.element.classList.remove('animating');
        
        if (this.animationFrameId) {
            cancelAnimationFrame(this.animationFrameId);
            this.animationFrameId = null;
        }
    }

    /**
     * 更新无障碍属性
     */
    updateAccessibility(isExpanded) {
        if (!this.options.accessibility) return;

        if (this.trigger) {
            this.trigger.setAttribute('aria-expanded', isExpanded);
        }
        if (this.content) {
            this.content.setAttribute('aria-hidden', !isExpanded);
        }
    }

    /**
     * 更新配置
     */
    updateOptions(newOptions) {
        this.options = { ...this.options, ...newOptions };
        this.applyCSSVariables();
    }

    /**
     * 获取当前状态
     */
    getState() {
        return this.state;
    }

    /**
     * 检查是否正在动画
     */
    getIsAnimating() {
        return this.isAnimating;
    }

    /**
     * 销毁组件
     */
    destroy() {
        if (this.animationFrameId) {
            cancelAnimationFrame(this.animationFrameId);
        }
        
        if (this.trigger) {
            this.trigger.removeEventListener('click', this.handleTriggerClick);
            this.trigger.removeEventListener('keydown', this.handleKeyDown);
        }

        this.element.classList.remove('collapse-animated');
        this.element.classList.remove('collapsed');
        this.element.classList.remove('expanded');
        this.element.classList.remove('animating');
        this.element.classList.remove('hardware-accelerated');
        this.element.classList.remove('reduce-reflow');
    }
}

// 静态方法：批量初始化
CollapseAnimated.initAll = function(selector = '.collapse-animated-container', options = {}) {
    const elements = document.querySelectorAll(selector);
    const instances = [];
    
    elements.forEach((element, index) => {
        const instance = new CollapseAnimated(element, {
            ...options,
            contentSelector: options.contentSelector || `.collapse-content-${index}`
        });
        instances.push(instance);
    });
    
    return instances;
};

// 导出为全局对象
if (typeof window !== 'undefined') {
    window.CollapseAnimated = CollapseAnimated;
}

// 导出为模块
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CollapseAnimated;
}
