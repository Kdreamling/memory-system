/**
 * 承诺墙页面 JavaScript
 */

const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:8003' : '';

const BY_MAP = {
    'Dream': 'Dream 🌙',
    'Claude': '晨 ☀️',
    '一起': '一起 💕'
};

let currentFilter = null;
let isLoading = false;

const pendingSection = document.getElementById('pendingSection');
const doneSection = document.getElementById('doneSection');
const pendingList = document.getElementById('pendingList');
const doneList = document.getElementById('doneList');
const loading = document.getElementById('loading');
const emptyState = document.getElementById('emptyState');
const errorState = document.getElementById('errorState');
const filterTabs = document.querySelectorAll('.filter-tab');

document.addEventListener('DOMContentLoaded', () => {
    loadPromises();
    setupFilterTabs();
});

function setupFilterTabs() {
    filterTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const by = tab.dataset.by;
            if (by === currentFilter || (by === 'all' && !currentFilter)) return;

            filterTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            currentFilter = by === 'all' ? null : by;
            loadPromises();
        });
    });
}

async function loadPromises() {
    if (isLoading) return;
    isLoading = true;

    loading.style.display = 'block';
    pendingSection.style.display = 'none';
    doneSection.style.display = 'none';
    emptyState.style.display = 'none';
    errorState.style.display = 'none';

    try {
        let url = `${API_BASE}/api/promises`;
        if (currentFilter) {
            url += `?promised_by=${encodeURIComponent(currentFilter)}`;
        }

        const response = await fetch(url);
        if (!response.ok) throw new Error('API 请求失败');

        const result = await response.json();
        if (!result.success) throw new Error('获取承诺失败');

        loading.style.display = 'none';

        if (result.data.length === 0) {
            emptyState.style.display = 'block';
            return;
        }

        const pending = result.data.filter(r => r.status === 'pending');
        const done = result.data.filter(r => r.status === 'done');

        pendingList.innerHTML = '';
        doneList.innerHTML = '';

        if (pending.length > 0) {
            pendingSection.style.display = 'block';
            pending.forEach(item => pendingList.appendChild(createCard(item, false)));
        }

        if (done.length > 0) {
            doneSection.style.display = 'block';
            done.forEach(item => doneList.appendChild(createCard(item, true)));
        }

    } catch (error) {
        console.error('加载承诺失败:', error);
        loading.style.display = 'none';
        errorState.style.display = 'block';
    } finally {
        isLoading = false;
    }
}

function createCard(item, isDone) {
    const card = document.createElement('div');
    card.className = `promise-card${isDone ? ' done' : ''}`;

    const byDisplay = BY_MAP[item.promised_by] || item.promised_by;
    const date = formatDate(item.date);

    let html = `
        <div class="promise-content">${escapeHtml(item.content)}</div>
        <div class="promise-meta">
            <span class="promise-by">${byDisplay}</span>
            <span class="promise-date">${date}</span>
            ${isDone ? '<span class="promise-done-mark">✅ 已兑现</span>' : ''}
        </div>
    `;

    card.innerHTML = html;
    return card;
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    try {
        const date = new Date(dateStr);
        return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
    } catch {
        return dateStr;
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

window.loadPromises = loadPromises;
