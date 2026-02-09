/**
 * 对话记忆页面 JavaScript
 */

// API 配置
const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:8003'
    : '';

// 状态
let currentCategory = null;
let currentKeyword = '';
let currentOffset = 0;
const PAGE_SIZE = 20;
let isLoading = false;
let hasMore = true;

// 心情映射
const MOOD_MAP = {
    '开心': '😄',
    '幸福': '🥰',
    '平静': '😌',
    '想念': '🥺',
    '担心': '😟',
    'emo': '😢',
    '兴奋': '🤩'
};

// 分类 CSS class 映射
const CATEGORY_CLASS_MAP = {
    '日常': 'cat-daily',
    '技术': 'cat-tech',
    '剧本': 'cat-script',
    '亲密': 'cat-intimate',
    '情感': 'cat-emotion',
    '工作': 'cat-work'
};

// DOM 元素
const memoriesList = document.getElementById('memoriesList');
const loading = document.getElementById('loading');
const loadMore = document.getElementById('loadMore');
const loadMoreBtn = document.getElementById('loadMoreBtn');
const emptyState = document.getElementById('emptyState');
const errorState = document.getElementById('errorState');
const filterTabs = document.querySelectorAll('.filter-tab');
const searchInput = document.getElementById('searchInput');

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    loadMemories();
    setupFilterTabs();
    setupLoadMore();
    setupSearch();
});

// 设置分类筛选
function setupFilterTabs() {
    filterTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const category = tab.dataset.category;
            if (category === currentCategory || (category === 'all' && !currentCategory)) return;

            filterTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            currentCategory = category === 'all' ? null : category;
            currentOffset = 0;
            hasMore = true;
            memoriesList.innerHTML = '';
            loadMemories();
        });
    });
}

// 设置加载更多
function setupLoadMore() {
    loadMoreBtn.addEventListener('click', () => {
        if (!isLoading && hasMore) {
            loadMemories(true);
        }
    });
}

// 设置搜索（防抖）
function setupSearch() {
    let timer = null;
    searchInput.addEventListener('input', () => {
        clearTimeout(timer);
        timer = setTimeout(() => {
            const keyword = searchInput.value.trim();
            if (keyword === currentKeyword) return;

            currentKeyword = keyword;
            currentOffset = 0;
            hasMore = true;
            memoriesList.innerHTML = '';
            loadMemories();
        }, 400);
    });
}

// 加载记忆
async function loadMemories(append = false) {
    if (isLoading) return;
    isLoading = true;

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
        let url = `${API_BASE}/api/chat_memories?limit=${PAGE_SIZE}&offset=${currentOffset}`;
        if (currentCategory) {
            url += `&category=${encodeURIComponent(currentCategory)}`;
        }
        if (currentKeyword) {
            url += `&keyword=${encodeURIComponent(currentKeyword)}`;
        }

        const response = await fetch(url);
        if (!response.ok) {
            throw new Error('API 请求失败');
        }

        const result = await response.json();

        if (!result.success) {
            throw new Error(result.detail || '获取记忆失败');
        }

        const memories = result.data;
        loading.style.display = 'none';

        if (memories.length === 0 && currentOffset === 0) {
            emptyState.style.display = 'block';
            loadMore.style.display = 'none';
        } else {
            memories.forEach(memory => {
                memoriesList.appendChild(createMemoryCard(memory));
            });

            currentOffset += memories.length;
            hasMore = memories.length === PAGE_SIZE;
            loadMore.style.display = hasMore ? 'block' : 'none';
        }

    } catch (error) {
        console.error('加载记忆失败:', error);
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

// 创建记忆卡片
function createMemoryCard(memory) {
    const card = document.createElement('article');
    card.className = 'memory-card';

    const date = formatDate(memory.chat_date);
    const categoryClass = CATEGORY_CLASS_MAP[memory.category] || 'cat-daily';
    const moodEmoji = MOOD_MAP[memory.mood] || '';

    let html = `
        <div class="memory-meta">
            <span class="memory-date">${date}</span>
            <span class="memory-category ${categoryClass}">${escapeHtml(memory.category || '')}</span>
        </div>
        <h3 class="memory-title">${escapeHtml(memory.chat_title || '')}</h3>
    `;

    if (memory.mood) {
        html += `<span class="memory-mood">${moodEmoji} ${escapeHtml(memory.mood)}</span>`;
    }

    const summary = memory.summary || '';
    const isLong = summary.length > 200;
    const cardId = `summary-${memory.id}`;

    html += `
        <div class="memory-summary ${isLong ? 'truncated' : ''}" id="${cardId}">
            ${escapeHtml(summary)}
        </div>
    `;

    if (isLong) {
        html += `
            <button class="expand-btn" onclick="toggleContent('${cardId}', this)">
                展开全文
            </button>
        `;
    }

    if (memory.tags && memory.tags.length > 0) {
        const tagsHtml = memory.tags.map(tag => `<span class="memory-tag">${escapeHtml(tag)}</span>`).join('');
        html += `<div class="memory-tags">${tagsHtml}</div>`;
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
window.loadMemories = loadMemories;
window.toggleContent = toggleContent;
