/**
 * Tab System JavaScript
 * Provides tab navigation functionality
 */

(function() {
    'use strict';

    // Initialize tab system when DOM is ready
    document.addEventListener('DOMContentLoaded', function() {
        initTabs();
    });

    function initTabs() {
        // Find all tab containers
        document.querySelectorAll('[data-tab-container]').forEach(function(container) {
            const tabs = container.querySelectorAll('[data-tab]');
            const panels = container.querySelectorAll('[data-tab-panel]');

            tabs.forEach(function(tab) {
                tab.addEventListener('click', function() {
                    const tabId = this.getAttribute('data-tab');

                    // Deactivate all tabs in this container
                    tabs.forEach(function(t) {
                        t.classList.remove('active');
                    });

                    // Deactivate all panels in this container
                    panels.forEach(function(p) {
                        p.classList.remove('active');
                    });

                    // Activate clicked tab
                    this.classList.add('active');

                    // Activate corresponding panel
                    const panel = container.querySelector('[data-tab-panel="' + tabId + '"]');
                    if (panel) {
                        panel.classList.add('active');
                    }

                    // Trigger custom event
                    const event = new CustomEvent('tabChange', {
                        detail: { tabId: tabId, container: container }
                    });
                    container.dispatchEvent(event);
                });
            });

            // Keyboard navigation
            container.addEventListener('keydown', function(e) {
                if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                    const activeTab = container.querySelector('[data-tab].active');
                    if (!activeTab) return;

                    const tabs = Array.from(container.querySelectorAll('[data-tab]'));
                    const currentIndex = tabs.indexOf(activeTab);
                    let newIndex;

                    if (e.key === 'ArrowLeft') {
                        newIndex = currentIndex > 0 ? currentIndex - 1 : tabs.length - 1;
                    } else {
                        newIndex = currentIndex < tabs.length - 1 ? currentIndex + 1 : 0;
                    }

                    tabs[newIndex].click();
                    tabs[newIndex].focus();
                }
            });
        });
    }

    // Export for manual use
    window.TabSystem = {
        init: initTabs,
        switchTab: function(containerId, tabId) {
            const container = document.getElementById(containerId);
            if (!container) return;

            const tab = container.querySelector('[data-tab="' + tabId + '"]');
            if (tab) {
                tab.click();
            }
        }
    };
})();
