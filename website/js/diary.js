/**
 * 日记页面 JavaScript
 */

// API 配置
// 本地开发用 localhost:8003，生产环境用 /api（Nginx 反代）
const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:8003'
    : '';

// 状态
let currentSource = 'all';
let currentOffset = 0;
const PAGE_SIZE = 10;
let isLoading = false;
let hasMore = true;

// DOM 元素
const diaryList = document.getElementById('diaryList');
const loading = document.getElementById('loading');
const loadMore = document.getElementById('loadMore');
const loadMoreBtn = document.getElementById('loadMoreBtn');
const emptyState = document.getElementById('emptyState');
const errorState = document.getElementById('errorState');
const filterTabs = document.querySelectorAll('.filter-tab');

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    loadDiaries();
    setupFilterTabs();
    setupLoadMore();
});

// 设置筛选标签
function setupFilterTabs() {
    filterTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const source = tab.dataset.source;
            if (source === currentSource) return;

            // 更新激活状态
            filterTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            // 重新加载
            currentSource = source === 'all' ? null : source;
            currentOffset = 0;
            hasMore = true;
            diaryList.innerHTML = '';
            loadDiaries();
        });
    });
}

// 设置加载更多
function setupLoadMore() {
    loadMoreBtn.addEventListener('click', () => {
        if (!isLoading && hasMore) {
            loadDiaries(true);
        }
    });
}

// 加载日记
async function loadDiaries(append = false) {
    if (isLoading) return;
    isLoading = true;

    // 显示/隐藏状态
    if (!append) {
        loading.style.display = 'block';
        emptyState.style.display = 'none';
        errorState.style.display = 'none';
        loadMore.style.display = 'none';
    } else {
        loadMoreBtn.disabled = true;
        loadMoreBtn.textContent = '加载中...';
    }

    try {
        let url = `${API_BASE}/api/diaries?limit=${PAGE_SIZE}&offset=${currentOffset}`;
        if (currentSource) {
            url += `&source=${currentSource}`;
        }

        const response = await fetch(url);
        if (!response.ok) {
            throw new Error('API 请求失败');
        }

        const result = await response.json();

        if (!result.success) {
            throw new Error(result.detail || '获取日记失败');
        }

        const diaries = result.data;

        // 隐藏加载状态
        loading.style.display = 'none';

        if (diaries.length === 0 && currentOffset === 0) {
            // 没有数据
            emptyState.style.display = 'block';
            loadMore.style.display = 'none';
        } else {
            // 渲染日记
            diaries.forEach(diary => {
                diaryList.appendChild(createDiaryCard(diary));
            });

            // 更新分页
            currentOffset += diaries.length;
            hasMore = diaries.length === PAGE_SIZE;

            // 显示/隐藏加载更多按钮
            loadMore.style.display = hasMore ? 'block' : 'none';
        }

    } catch (error) {
        console.error('加载日记失败:', error);
        loading.style.display = 'none';

        if (currentOffset === 0) {
            errorState.style.display = 'block';
        }
    } finally {
        isLoading = false;
        loadMoreBtn.disabled = false;
        loadMoreBtn.textContent = '加载更多';
    }
}

// 创建日记卡片
function createDiaryCard(diary) {
    const card = document.createElement('article');
    card.className = 'diary-card';

    // 格式化日期
    const date = formatDate(diary.diary_date);

    // 来源图标
    const sourceIcon = diary.source === 'chen'
        ? '<svg class="diary-source-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>'
        : '<svg class="diary-source-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>';

    let html = `
        <div class="diary-meta">
            <span class="diary-date">${date}</span>
            <span class="diary-source ${diary.source}">${sourceIcon} ${diary.source_name}</span>
        </div>
    `;

    // 晨的日记显示心情和亮点
    if (diary.source === 'chen') {
        if (diary.mood) {
            html += `
                <div class="diary-mood">
                    <span class="diary-mood-label">今日心情:</span>
                    <span class="diary-mood-value">${escapeHtml(diary.mood)}</span>
                </div>
            `;
        }
        if (diary.highlights) {
            html += `
                <div class="diary-highlights">
                    <div class="diary-highlights-label">今日亮点</div>
                    <div class="diary-highlights-value">${escapeHtml(diary.highlights)}</div>
                </div>
            `;
        }
    }

    // 内容
    const content = diary.content || '';
    const isLong = content.length > 300;
    const contentId = `content-${diary.id}-${diary.source}`;

    html += `
        <div class="diary-content ${isLong ? 'truncated' : ''}" id="${contentId}">
            ${escapeHtml(content)}
        </div>
    `;

    if (isLong) {
        html += `
            <button class="expand-btn" onclick="toggleContent('${contentId}', this)">
                展开全文
            </button>
        `;
    }

    card.innerHTML = html;
    return card;
}

// 展开/收起内容
function toggleContent(contentId, btn) {
    const content = document.getElementById(contentId);
    if (content.classList.contains('truncated')) {
        content.classList.remove('truncated');
        btn.textContent = '收起';
    } else {
        content.classList.add('truncated');
        btn.textContent = '展开全文';
    }
}

// 格式化日期
function formatDate(dateStr) {
    if (!dateStr) return '未知日期';

    try {
        const date = new Date(dateStr);
        const year = date.getFullYear();
        const month = date.getMonth() + 1;
        const day = date.getDate();
        const weekDays = ['日', '一', '二', '三', '四', '五', '六'];
        const weekDay = weekDays[date.getDay()];

        return `${year}年${month}月${day}日 周${weekDay}`;
    } catch {
        return dateStr;
    }
}

// HTML 转义
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 暴露给全局
window.loadDiaries = loadDiaries;
window.toggleContent = toggleContent;
