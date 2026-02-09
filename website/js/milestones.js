/**
 * 编年史页面 JavaScript
 */

const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:8003' : '';

let currentTag = null;
let isLoading = false;

const TAG_CLASS_MAP = {
    '第一次': 'tag-first',
    '纪念日': 'tag-anniversary',
    '转折点': 'tag-turning'
};

const timelineContainer = document.getElementById('timelineContainer');
const loading = document.getElementById('loading');
const emptyState = document.getElementById('emptyState');
const errorState = document.getElementById('errorState');
const filterTabs = document.querySelectorAll('.filter-tab');

document.addEventListener('DOMContentLoaded', () => {
    loadMilestones();
    setupFilterTabs();
});

function setupFilterTabs() {
    filterTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const tag = tab.dataset.tag;
            if (tag === currentTag || (tag === 'all' && !currentTag)) return;

            filterTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            currentTag = tag === 'all' ? null : tag;
            timelineContainer.innerHTML = '';
            loadMilestones();
        });
    });
}

async function loadMilestones() {
    if (isLoading) return;
    isLoading = true;

    loading.style.display = 'block';
    emptyState.style.display = 'none';
    errorState.style.display = 'none';

    try {
        let url = `${API_BASE}/api/milestones`;
        if (currentTag) {
            url += `?tag=${encodeURIComponent(currentTag)}`;
        }

        const response = await fetch(url);
        if (!response.ok) throw new Error('API 请求失败');

        const result = await response.json();
        if (!result.success) throw new Error('获取里程碑失败');

        loading.style.display = 'none';

        if (result.data.length === 0) {
            emptyState.style.display = 'block';
        } else {
            result.data.forEach(item => {
                timelineContainer.appendChild(createTimelineItem(item));
            });
        }

    } catch (error) {
        console.error('加载里程碑失败:', error);
        loading.style.display = 'none';
        errorState.style.display = 'block';
    } finally {
        isLoading = false;
    }
}

function createTimelineItem(item) {
    const el = document.createElement('div');
    el.className = 'timeline-item';

    const tagClass = TAG_CLASS_MAP[item.tag] || 'tag-first';
    const date = formatDate(item.date);

    let html = `
        <div class="timeline-card">
            <div class="timeline-date">${date}</div>
            <div class="timeline-event">${escapeHtml(item.event)}</div>
    `;

    if (item.note) {
        html += `<div class="timeline-note">${escapeHtml(item.note)}</div>`;
    }

    html += `<span class="timeline-tag ${tagClass}">${escapeHtml(item.tag)}</span>
        </div>
    `;

    el.innerHTML = html;
    return el;
}

function formatDate(dateStr) {
    if (!dateStr) return '未知日期';
    try {
        const date = new Date(dateStr);
        const year = date.getFullYear();
        const month = date.getMonth() + 1;
        const day = date.getDate();
        return `${year}年${month}月${day}日`;
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

window.loadMilestones = loadMilestones;
