/**
 * 通用分页组件
 * 用法：renderPagination(data, containerId, loadFn)
 * - data: { items, total, pages, current_page }
 * - containerId: 分页导航元素的 ID
 * - loadFn: 加载指定页的函数 loadFn(page)
 */
function renderPagination(data, containerId, loadFn) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const totalPages = data.pages || 1;
    const currentPage = data.current_page || 1;
    const total = data.total || 0;

    if (totalPages <= 1) {
        container.innerHTML = `<span class="text-muted small">共 ${total} 条记录</span>`;
        return;
    }

    let html = `<nav aria-label="分页导航"><ul class="pagination pagination-sm mb-0">`;

    // 上一页
    html += `<li class="page-item ${currentPage <= 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${currentPage - 1}" aria-label="上一页">&laquo;</a>
    </li>`;

    // 页码（最多显示7个）
    let startPage = Math.max(1, currentPage - 3);
    let endPage = Math.min(totalPages, startPage + 6);
    startPage = Math.max(1, endPage - 6);

    if (startPage > 1) {
        html += `<li class="page-item"><a class="page-link" href="#" data-page="1">1</a></li>`;
        if (startPage > 2) html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
    }

    for (let i = startPage; i <= endPage; i++) {
        html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
            <a class="page-link" href="#" data-page="${i}">${i}</a>
        </li>`;
    }

    if (endPage < totalPages) {
        if (endPage < totalPages - 1) html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        html += `<li class="page-item"><a class="page-link" href="#" data-page="${totalPages}">${totalPages}</a></li>`;
    }

    // 下一页
    html += `<li class="page-item ${currentPage >= totalPages ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${currentPage + 1}" aria-label="下一页">&raquo;</a>
    </li>`;

    html += `</ul></nav>`;
    html += `<span class="text-muted small ms-3">共 ${total} 条，第 ${currentPage}/${totalPages} 页</span>`;

    container.innerHTML = html;

    // 绑定点击事件
    container.querySelectorAll('.page-link[data-page]').forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const page = parseInt(this.dataset.page);
            if (page >= 1 && page <= totalPages && page !== currentPage) {
                loadFn(page);
            }
        });
    });
}
