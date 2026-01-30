import { createSeparatorElement } from './components/separator/index.js';
import { createMessageHtml } from './components/message/index.js';
import { htmlToElement, resolveMediaUrl, applyImageFallback } from './utils.js';

// 绑定按钮
document.getElementById('confirmSearch').addEventListener('click', searchMessages);

// 初始化聊天数据
let allMessages = [];
const overlay = document.getElementById('overlay');
overlay.classList.remove('hidden');
const topLoader = document.getElementById('topLoader');
const toastEl = document.getElementById('chatToast');
const chatId = window.CHAT_ID;
const pageSize = 20;
let searchGapCounter = 0;
let latestChatMsgId = null;
let oldestIndex = 0;
let totalMessages = 0;

let isReactionSorting = false;
let reactionEmoticon = '';
let reactionOffset = 0;
let reactionTotal = 0;
let isLoadingReactionMessages = false;

if ('scrollRestoration' in history) {
    history.scrollRestoration = 'manual';
}

function nextTick() {
    return new Promise(resolve => setTimeout(resolve, 0));
}

function nextFrame() {
    return new Promise(resolve => requestAnimationFrame(resolve));
}

let _toastTimer = null;
function showToast(message, variant = 'info') {
    if (!toastEl) return;
    toastEl.textContent = String(message ?? '');
    toastEl.classList.remove('chat-toast--error', 'chat-toast--show');
    if (variant === 'error') toastEl.classList.add('chat-toast--error');
    void toastEl.offsetWidth;
    toastEl.classList.add('chat-toast--show');
    if (_toastTimer) clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => {
        toastEl.classList.remove('chat-toast--show');
    }, 2600);
}

function isInViewport(el, margin = 200) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    return rect.bottom >= -margin && rect.top <= (window.innerHeight + margin);
}

function isPageScrollable() {
    return document.body.scrollHeight > window.innerHeight + 10;
}

let _imageViewer = null;
function ensureImageViewer() {
    if (_imageViewer) return _imageViewer;

    const root = document.createElement('div');
    root.id = 'imageViewer';
    root.className = 'image-viewer hidden';
    root.innerHTML = `
      <div class="image-viewer__backdrop" data-action="close"></div>
      <div class="image-viewer__content" role="dialog" aria-modal="true">
        <button type="button" class="image-viewer__nav image-viewer__nav--prev" data-action="prev" aria-label="上一张">‹</button>
        <button type="button" class="image-viewer__nav image-viewer__nav--next" data-action="next" aria-label="下一张">›</button>
        <button type="button" class="image-viewer__close" data-action="close" aria-label="关闭">×</button>
        <img class="image-viewer__img" data-action="close" data-role="img" alt="图片预览" />
      </div>
    `;
    document.body.appendChild(root);

    const img = root.querySelector('[data-role="img"]');
    img.addEventListener('error', () => applyImageFallback(img));

    let items = [];
    let index = 0;

    const close = () => {
        root.classList.add('hidden');
        document.body.classList.remove('no-scroll');
    };

    const showAt = (nextIndex) => {
        if (!items || items.length === 0) return;
        const len = items.length;
        index = ((Number(nextIndex) % len) + len) % len;
        const src = resolveMediaUrl(items[index]);
        if (!src) return;
        img.dataset.fallbackApplied = '0';
        img.classList.remove('img-broken');
        img.src = src;

        const prevBtn = root.querySelector('.image-viewer__nav--prev');
        const nextBtn = root.querySelector('.image-viewer__nav--next');
        const showNav = len > 1;
        if (prevBtn) prevBtn.style.display = showNav ? 'block' : 'none';
        if (nextBtn) nextBtn.style.display = showNav ? 'block' : 'none';
    };

    const setGallery = (nextItems, nextIndex) => {
        items = Array.isArray(nextItems) ? nextItems.filter(Boolean) : [];
        index = Number.isFinite(Number(nextIndex)) ? Number(nextIndex) : 0;
        showAt(index);
    };

    root.addEventListener('click', (e) => {
        const action = e.target?.dataset?.action;
        if (action === 'close') close();
        if (action === 'prev') showAt(index - 1);
        if (action === 'next') showAt(index + 1);
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !root.classList.contains('hidden')) close();
        if (root.classList.contains('hidden')) return;
        if (e.key === 'ArrowLeft') showAt(index - 1);
        if (e.key === 'ArrowRight') showAt(index + 1);
    });

    _imageViewer = {
        root,
        img,
        close,
        setGallery
    };
    return _imageViewer;
}

function openImageViewer(url) {
    const src = resolveMediaUrl(url);
    if (!src) return;
    const viewer = ensureImageViewer();
    viewer.setGallery([src], 0);
    viewer.root.classList.remove('hidden');
    document.body.classList.add('no-scroll');
}

function openImageViewerFromTile(tile) {
    const imgSrc = tile?.dataset?.imgSrc;
    if (!imgSrc) return;
    const galleryRoot = tile.closest('.image-grid') || tile.closest('.reply-info') || tile.closest('.message-frame') || tile.closest('.message');
    const tiles = galleryRoot ? Array.from(galleryRoot.querySelectorAll('.img-tile[data-img-src]')) : [tile];
    const items = tiles.map(t => t.dataset?.imgSrc).filter(Boolean);
    const idx = Math.max(0, tiles.indexOf(tile));

    const viewer = ensureImageViewer();
    viewer.setGallery(items, idx);
    viewer.root.classList.remove('hidden');
    document.body.classList.add('no-scroll');
}

// 动态加载 JSON 数据
function fetchMessages(offset, limit) {
    return fetch(`../messages/${chatId}?offset=${offset}&limit=${limit}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('无法加载消息数据');
            }
            return response.json();
        });
}

async function ensureLatestChatMsgId() {
    if (latestChatMsgId !== null) return latestChatMsgId;
    try {
        const data = await fetchMessages(-1, 1);
        const m = Array.isArray(data.messages) ? data.messages[0] : null;
        latestChatMsgId = m && m.msg_id != null ? Number(m.msg_id) : null;
    } catch (e) {
        latestChatMsgId = null;
    }
    return latestChatMsgId;
}

function fetchSearchMessages(query, offset, limit) {
    return fetch(`../search/${chatId}?q=${encodeURIComponent(query)}&offset=${offset}&limit=${limit}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('无法加载搜索结果');
            }
            return response.json();
        });
}

function fetchReactionEmoticons() {
    return fetch(`../reactions_emoticons/${chatId}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('无法加载 reactions 表情列表');
            }
            return response.json();
        });
}

function fetchMessagesByReaction(emoticon, offset, limit) {
    return fetch(`../messages_by_reaction/${chatId}?emoticon=${encodeURIComponent(emoticon)}&offset=${offset}&limit=${limit}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('无法加载 reactions 排序消息');
            }
            return response.json();
        });
}

function fetchRepliesMessages(replyToMsgId, offset, limit) {
    return fetch(`../replies/${chatId}/${encodeURIComponent(replyToMsgId)}?offset=${offset}&limit=${limit}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('无法加载 replies 列表');
            }
            return response.json();
        });
}

function fetchMessagesByRepliesNum(offset, limit) {
    return fetch(`../messages_by_replies_num/${chatId}?offset=${offset}&limit=${limit}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('无法加载 replies_num 排序消息');
            }
            return response.json();
        });
}

async function downloadTelegramMediaForTile(tile) {
    if (!tile || tile.classList.contains('img-downloading')) return;

    const expectedUrl = tile.dataset?.imgSrc;
    if (!expectedUrl || !String(expectedUrl).startsWith('/downloads/')) {
        showToast('缺少 img_src，无法下载。', 'error');
        return;
    }

    function deriveTelegramUrlFromImgSrc(imgSrc) {
        const raw = String(imgSrc || '');
        const noQuery = raw.split('#')[0].split('?')[0];
        const parts = noQuery.split('/').filter(Boolean);
        if (parts.length === 0) return '';

        const filename = parts[parts.length - 1];
        const chunks = filename.split('_');
        if (chunks.length < 2) return '';
        const msgId = Number(chunks[1]);
        if (!Number.isFinite(msgId)) return '';

        const username = (window.CHAT_USERNAME || '').trim();
        if (username) return `https://t.me/${username}/${msgId}`;
        return `https://t.me/c/${chatId}/${msgId}`;
    }

    const messageEl = tile.closest('.message');
    const tiles = messageEl
        ? Array.from(messageEl.querySelectorAll('.img-tile[data-img-src]'))
        : [tile];

    const targets = tiles
        .map(t => {
            const img = t.querySelector('img');
            const imgSrc = t.dataset?.imgSrc;
            if (!img || !imgSrc || !String(imgSrc).startsWith('/downloads/')) return null;
            if (!img.classList.contains('img-broken')) return null;
            const telegramUrl = deriveTelegramUrlFromImgSrc(imgSrc);
            if (!telegramUrl) return null;
            return { tile: t, telegramUrl, expectedUrl: imgSrc };
        })
        .filter(Boolean);

    if (targets.length === 0) {
        showToast('没有需要下载的图片。', 'error');
        return;
    }

    for (const t of targets) {
        t.tile.classList.add('img-downloading');
    }
    try {
        const res = await fetch(`../download_telegram_media`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                chat_id: chatId,
                telegram_urls: targets.map(t => t.telegramUrl),
                expected_urls: targets.map(t => t.expectedUrl),
            }),
        });
        const data = await res.json().catch(() => ({}));
        const mediaUrls = Array.isArray(data?.media_urls) ? data.media_urls : [];
        if (!res.ok || !data || data.ok !== true || mediaUrls.length === 0) {
            showToast('下载失败，请稍后重试。', 'error');
            return;
        }

        const mapByExpected = new Map(
            mediaUrls
                .filter(it => it && it.expected_url && it.media_url)
                .map(it => [String(it.expected_url), String(it.media_url)])
        );

        const now = Date.now();
        for (const t of targets) {
            const mediaUrl = mapByExpected.get(String(t.expectedUrl));
            if (!mediaUrl) continue;
            t.tile.dataset.imgSrc = mediaUrl;
            const img = t.tile.querySelector('img');
            if (img) {
                img.dataset.fallbackApplied = '0';
                img.classList.remove('img-broken');
                const bust = mediaUrl.includes('?') ? `&v=${now}` : `?v=${now}`;
                img.src = mediaUrl + bust;
            }
        }

        showToast('已重新下载图片。');
    } catch (e) {
        showToast('下载失败，请稍后重试。', 'error');
    } finally {
        for (const t of targets) {
            t.tile.classList.remove('img-downloading');
        }
    }
}

async function downloadAllBrokenImages(batchSize = 10) {
    const btn = document.getElementById('downloadBrokenImages');
    if (btn) btn.disabled = true;

    const brokenImgs = Array.from(document.querySelectorAll('.img-tile[data-img-src] img.img-broken'));
    const tiles = brokenImgs
        .map(img => img.closest('.img-tile[data-img-src]'))
        .filter(Boolean);

    const deriveTelegramUrlFromImgSrc = (imgSrc) => {
        const raw = String(imgSrc || '');
        const noQuery = raw.split('#')[0].split('?')[0];
        const parts = noQuery.split('/').filter(Boolean);
        if (parts.length === 0) return '';

        const filename = parts[parts.length - 1];
        const chunks = filename.split('_');
        if (chunks.length < 2) return '';
        const msgId = Number(chunks[1]);
        if (!Number.isFinite(msgId)) return '';

        const username = (window.CHAT_USERNAME || '').trim();
        if (username) return `https://t.me/${username}/${msgId}`;
        return `https://t.me/c/${chatId}/${msgId}`;
    };

    const targets = tiles
        .map(tile => {
            const expectedUrl = tile.dataset?.imgSrc;
            if (!expectedUrl || !String(expectedUrl).startsWith('/downloads/')) return null;
            const telegramUrl = deriveTelegramUrlFromImgSrc(expectedUrl);
            if (!telegramUrl) return null;
            return { tile, telegramUrl, expectedUrl: String(expectedUrl) };
        })
        .filter(Boolean);

    if (targets.length === 0) {
        showToast('没有发现损坏图片。');
        if (btn) btn.disabled = false;
        return;
    }

    const total = targets.length;
    let done = 0;
    let success = 0;

    for (let i = 0; i < targets.length; i += batchSize) {
        const batch = targets.slice(i, i + batchSize);
        for (const t of batch) t.tile.classList.add('img-downloading');

        try {
            showToast(`下载中：${done}/${total}…`);
            const res = await fetch(`../download_telegram_media`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    chat_id: chatId,
                    telegram_urls: batch.map(t => t.telegramUrl),
                    expected_urls: batch.map(t => t.expectedUrl),
                }),
            });
            const data = await res.json().catch(() => ({}));
            const mediaUrls = Array.isArray(data?.media_urls) ? data.media_urls : [];
            if (!res.ok || !data || data.ok !== true || mediaUrls.length === 0) {
                showToast('批量下载失败（将继续下一批）。', 'error');
                continue;
            }

            const mapByExpected = new Map(
                mediaUrls
                    .filter(it => it && it.expected_url && it.media_url)
                    .map(it => [String(it.expected_url), String(it.media_url)])
            );

            const now = Date.now();
            for (const t of batch) {
                const mediaUrl = mapByExpected.get(String(t.expectedUrl));
                if (!mediaUrl) continue;
                success += 1;
                t.tile.dataset.imgSrc = mediaUrl;
                const img = t.tile.querySelector('img');
                if (img) {
                    img.dataset.fallbackApplied = '0';
                    img.classList.remove('img-broken');
                    const bust = mediaUrl.includes('?') ? `&v=${now}` : `?v=${now}`;
                    img.src = mediaUrl + bust;
                }
            }
        } catch (e) {
            showToast('批量下载失败（将继续下一批）。', 'error');
        } finally {
            done += batch.length;
            for (const t of batch) t.tile.classList.remove('img-downloading');
        }
    }

    showToast(`下载完成：成功 ${success}/${total}${success === total ? '。' : '（部分失败）'}`, success === total ? 'info' : 'error');
    if (btn) btn.disabled = false;
}

let _missingImagesPollTimer = null;
function stopMissingImagesPoll() {
    if (_missingImagesPollTimer) {
        clearInterval(_missingImagesPollTimer);
        _missingImagesPollTimer = null;
    }
}

async function startDownloadMissingImagesJob(batchSize = 10) {
    const btn = document.getElementById('downloadBrokenImages');
    if (btn) btn.disabled = true;

    stopMissingImagesPoll();

    try {
        const res = await fetch(`../download_missing_images`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chat_id: chatId, batch_size: batchSize }),
        });

        const data = await res.json().catch(() => ({}));
        if (res.status === 409) {
            showToast('下载任务已在运行，正在获取进度…');
            startMissingImagesPoll();
            return;
        }
        if (!res.ok || !data || !data.status) {
            showToast(data?.error || '启动下载失败，请重试。', 'error');
            if (btn) btn.disabled = false;
            return;
        }

        showToast('已启动下载（后台执行）。');
        startMissingImagesPoll();
    } catch (e) {
        showToast('启动下载失败，请重试。', 'error');
        if (btn) btn.disabled = false;
    }
}

function startMissingImagesPoll() {
    const btn = document.getElementById('downloadBrokenImages');

    const poll = () => {
        fetch(`../download_missing_images_status/${encodeURIComponent(chatId)}`)
            .then(r => r.json())
            .then(data => {
                if (!data || data.status === 'idle') {
                    stopMissingImagesPoll();
                    if (btn) btn.disabled = false;
                    return;
                }

                if (data.status === 'running') {
                    const total = Number(data.total_images ?? 0);
                    const processed = Number(data.processed_images ?? 0);
                    const downloaded = Number(data.downloaded_images ?? 0);
                    showToast(`下载中：${processed}/${total}（成功 ${downloaded}）…`);
                    return;
                }

                stopMissingImagesPoll();
                if (btn) btn.disabled = false;
                if (data.status === 'done') {
                    const total = Number(data.total_images ?? 0);
                    const downloaded = Number(data.downloaded_images ?? 0);
                    const failedBatches = Number(data.failed_batches ?? 0);
                    if (total === 0) {
                        showToast('没有缺失图片。');
                        return;
                    }
                    showToast(`下载完成：成功 ${downloaded}/${total}${failedBatches ? `，失败批次 ${failedBatches}` : ''}`);
                    return;
                }

                if (data.status === 'error') {
                    showToast(`下载失败：${data.last_error || '未知错误'}`, 'error');
                }
            })
            .catch(() => { });
    };

    poll();
    stopMissingImagesPoll();
    _missingImagesPollTimer = setInterval(poll, 2500);
}

function resetReactionSortingState() {
    isReactionSorting = false;
    reactionEmoticon = '';
    reactionOffset = 0;
    reactionTotal = 0;
    isLoadingReactionMessages = false;
}

function resetRepliesNumSortingState() {
    isRepliesNumSorting = false;
    repliesNumOffset = 0;
    repliesNumTotal = 0;
    isLoadingRepliesNumMessages = false;
}

let isRepliesViewing = false;
let repliesToMsgId = null;
let repliesOldestOffset = 0;
let repliesTotal = 0;
let isLoadingRepliesMessages = false;

let isRepliesNumSorting = false;
let repliesNumOffset = 0;
let repliesNumTotal = 0;
let isLoadingRepliesNumMessages = false;

let _previousViewState = null;

function resetRepliesViewState() {
    isRepliesViewing = false;
    repliesToMsgId = null;
    repliesOldestOffset = 0;
    repliesTotal = 0;
    isLoadingRepliesMessages = false;
    const btn = document.getElementById('exitReplies');
    if (btn) btn.classList.add('hidden');
}

function _snapshotCurrentViewState(focusMsgId) {
    const reactionSelect = document.getElementById('reactionSelect');
    const repliesNumSelect = document.getElementById('repliesNumSelect');
    const searchBox = document.getElementById('searchBox');
    return {
        focusMsgId: focusMsgId ?? null,
        html: messagesContainer.innerHTML,
        scrollY: window.scrollY,
        isSearching,
        searchQuery,
        searchOldestOffset,
        searchTotal,
        isReactionSorting,
        reactionEmoticon,
        reactionOffset,
        reactionTotal,
        isRepliesNumSorting,
        repliesNumOffset,
        repliesNumTotal,
        oldestIndex,
        totalMessages,
        latestChatMsgId,
        allMessages,
        currentStartIndex,
        ui: {
            reactionSelectValue: reactionSelect ? reactionSelect.value : '',
            repliesNumSelectValue: repliesNumSelect ? repliesNumSelect.value : '',
            searchBoxValue: searchBox ? searchBox.value : '',
        }
    };
}

async function _restorePreviousViewState() {
    if (!_previousViewState) return false;
    const state = _previousViewState;
    _previousViewState = null;

    resetRepliesViewState();

    messagesContainer.innerHTML = state.html || '';
    isSearching = !!state.isSearching;
    searchQuery = state.searchQuery || '';
    searchOldestOffset = Number(state.searchOldestOffset ?? 0);
    searchTotal = Number(state.searchTotal ?? 0);
    isLoadingSearchMessages = false;
    isReactionSorting = !!state.isReactionSorting;
    reactionEmoticon = state.reactionEmoticon || '';
    reactionOffset = Number(state.reactionOffset ?? 0);
    reactionTotal = Number(state.reactionTotal ?? 0);
    isLoadingReactionMessages = false;
    isRepliesNumSorting = !!state.isRepliesNumSorting;
    repliesNumOffset = Number(state.repliesNumOffset ?? 0);
    repliesNumTotal = Number(state.repliesNumTotal ?? 0);
    isLoadingRepliesNumMessages = false;
    oldestIndex = Number(state.oldestIndex ?? 0);
    totalMessages = Number(state.totalMessages ?? 0);
    latestChatMsgId = state.latestChatMsgId ?? null;
    allMessages = Array.isArray(state.allMessages) ? state.allMessages : [];
    currentStartIndex = Number(state.currentStartIndex ?? allMessages.length);
    isLoadingOlderMessages = false;

    const reactionSelect = document.getElementById('reactionSelect');
    if (reactionSelect) reactionSelect.value = state.ui?.reactionSelectValue ?? '';
    const repliesNumSelect = document.getElementById('repliesNumSelect');
    if (repliesNumSelect) repliesNumSelect.value = state.ui?.repliesNumSelectValue ?? '';
    const searchBox = document.getElementById('searchBox');
    if (searchBox) searchBox.value = state.ui?.searchBoxValue ?? '';

    await nextTick();
    await waitForMediaToLoad();

    if (state.focusMsgId != null) {
        const el = messagesContainer.querySelector(`.message[data-msg-id="${state.focusMsgId}"]`);
        if (el) {
            el.scrollIntoView({ block: 'center' });
            nextTick()
                .then(() => waitForMediaToLoad())
                .then(() => el.scrollIntoView({ block: 'center' }))
                .catch(() => { });
            return true;
        }
    }

    const scrollY = Number(state.scrollY ?? 0);
    if (Number.isFinite(scrollY)) {
        window.scrollTo(0, scrollY);
        return true;
    }
    return false;
}

function exitRepliesView() {
    if (!isRepliesViewing) return;
    _restorePreviousViewState()
        .catch(() => {
            resetRepliesViewState();
            messagesContainer.innerHTML = '';
            overlay.classList.remove('hidden');
            loadMessages();
        });
}

function setReactionSorting(emoticon) {
    const picked = (emoticon || '').trim();
    if (!picked) {
        resetReactionSortingState();
        resetRepliesViewState();
        resetRepliesNumSortingState();
        const repliesNumSelect = document.getElementById('repliesNumSelect');
        if (repliesNumSelect) repliesNumSelect.value = '';
        messagesContainer.innerHTML = '';
        loadMessages();
        return;
    }

    isSearching = false;
    resetRepliesViewState();
    resetRepliesNumSortingState();
    const repliesNumSelect = document.getElementById('repliesNumSelect');
    if (repliesNumSelect) repliesNumSelect.value = '';
    isReactionSorting = true;
    reactionEmoticon = picked;
    reactionOffset = 0;
    reactionTotal = 0;
    messagesContainer.innerHTML = '';
    overlay.classList.remove('hidden');
    loadMoreReactionMessages(true);
}

async function loadMoreReactionMessages(isInitial = false) {
    if (!isReactionSorting || isLoadingReactionMessages) return;
    if (!isInitial && reactionTotal > 0 && reactionOffset >= reactionTotal) return;

    isLoadingReactionMessages = true;
    try {
        const data = await fetchMessagesByReaction(reactionEmoticon, reactionOffset, pageSize);
        reactionTotal = data.total || 0;
        const batch = Array.isArray(data.messages) ? data.messages : [];
        if (batch.length === 0) return;

        reactionOffset += batch.length;

        // 为了保持“聊天”阅读习惯：把 Count 更高的放在更靠下的位置（底部最重要）
        const ordered = batch.slice().reverse();

        let html = '';
        for (const m of ordered) {
            html += createMessageHtml(m, m.msg_id, '');
        }

        if (isInitial) {
            messagesContainer.innerHTML = html;
            await nextTick();
            await waitForMediaToLoad();
            window.scrollTo(0, document.body.scrollHeight);
        } else {
            const prevHeight = document.body.scrollHeight;
            messagesContainer.insertAdjacentHTML('afterbegin', html);
            await nextTick();
            await waitForMediaToLoad();
            const newHeight = document.body.scrollHeight;
            window.scrollTo(0, window.scrollY + (newHeight - prevHeight));
        }
    } catch (error) {
        console.error('加载 reactions 排序消息失败:', error);
    } finally {
        isLoadingReactionMessages = false;
        if (isInitial) overlay.classList.add('hidden');
    }
}

function setRepliesNumSorting(modeValue) {
    const picked = (modeValue || '').trim();
    if (!picked) {
        resetRepliesNumSortingState();
        resetRepliesViewState();
        messagesContainer.innerHTML = '';
        loadMessages();
        return;
    }

    if (isRepliesViewing) {
        _previousViewState = null;
        resetRepliesViewState();
    }

    if (isReactionSorting) {
        resetReactionSortingState();
        const reactionSelect = document.getElementById('reactionSelect');
        if (reactionSelect) reactionSelect.value = '';
    }

    if (isSearching) {
        isSearching = false;
        searchQuery = '';
        searchOldestOffset = 0;
        searchTotal = 0;
        isLoadingSearchMessages = false;
        updateSearchMoreResultsButton();
        const searchBox = document.getElementById('searchBox');
        if (searchBox) searchBox.value = '';
    }

    isRepliesNumSorting = true;
    repliesNumOffset = 0;
    repliesNumTotal = 0;
    isLoadingRepliesNumMessages = false;
    messagesContainer.innerHTML = '';
    overlay.classList.remove('hidden');
    loadMoreRepliesNumMessages(true);
}

async function loadMoreRepliesNumMessages(isInitial = false) {
    if (!isRepliesNumSorting || isLoadingRepliesNumMessages) return;
    if (!isInitial && repliesNumTotal > 0 && repliesNumOffset >= repliesNumTotal) return;

    isLoadingRepliesNumMessages = true;
    try {
        const data = await fetchMessagesByRepliesNum(repliesNumOffset, pageSize);
        repliesNumTotal = data.total || 0;
        const batch = Array.isArray(data.messages) ? data.messages : [];
        if (batch.length === 0) return;

        repliesNumOffset += batch.length;

        const ordered = batch.slice().reverse();
        let html = '';
        for (const m of ordered) {
            html += createMessageHtml(m, m.msg_id, '');
        }

        if (isInitial) {
            messagesContainer.innerHTML = html;
            await nextTick();
            await waitForMediaToLoad();
            window.scrollTo(0, document.body.scrollHeight);
        } else {
            const prevHeight = document.body.scrollHeight;
            messagesContainer.insertAdjacentHTML('afterbegin', html);
            await nextTick();
            await waitForMediaToLoad();
            const newHeight = document.body.scrollHeight;
            window.scrollTo(0, window.scrollY + (newHeight - prevHeight));
        }
    } catch (error) {
        console.error('加载 replies_num 排序消息失败:', error);
    } finally {
        isLoadingRepliesNumMessages = false;
        if (isInitial) overlay.classList.add('hidden');
    }
}

async function setRepliesView(targetMsgId) {
    const mid = Number(targetMsgId);
    if (!Number.isFinite(mid)) return;

    if (isRepliesViewing && repliesToMsgId === mid) {
        exitRepliesView();
        return;
    }

    if (!isRepliesViewing) {
        _previousViewState = _snapshotCurrentViewState(mid);
    }

    if (isReactionSorting) {
        resetReactionSortingState();
        const reactionSelect = document.getElementById('reactionSelect');
        if (reactionSelect) reactionSelect.value = '';
    }

    if (isRepliesNumSorting) {
        resetRepliesNumSortingState();
        const repliesNumSelect = document.getElementById('repliesNumSelect');
        if (repliesNumSelect) repliesNumSelect.value = '';
    }

    if (isSearching) {
        isSearching = false;
        searchQuery = '';
        searchOldestOffset = 0;
        searchTotal = 0;
        isLoadingSearchMessages = false;
        updateSearchMoreResultsButton();
        const searchBox = document.getElementById('searchBox');
        if (searchBox) searchBox.value = '';
    }

    isRepliesViewing = true;
    repliesToMsgId = mid;
    repliesOldestOffset = 0;
    repliesTotal = 0;
    isLoadingRepliesMessages = false;

    const btn = document.getElementById('exitReplies');
    if (btn) btn.classList.remove('hidden');

    messagesContainer.innerHTML = '';
    overlay.classList.remove('hidden');
    try {
        const data = await fetchRepliesMessages(mid, -pageSize, pageSize);
        const batch = Array.isArray(data.messages) ? data.messages : [];
        repliesOldestOffset = Number(data.offset ?? 0);
        repliesTotal = Number(data.total ?? 0);

        const frag = document.createDocumentFragment();
        for (const m of batch) {
            const idx = (m.msg_id ?? Math.random());
            const el = htmlToElement(createMessageHtml(m, idx, ''));
            if (el) frag.appendChild(el);
        }
        messagesContainer.innerHTML = '';
        messagesContainer.appendChild(frag);

        await nextTick();
        await waitForMediaToLoad();
        window.scrollTo(0, document.body.scrollHeight);
    } catch (error) {
        console.error('加载 replies 列表失败:', error);
    } finally {
        overlay.classList.add('hidden');
    }
}

async function loadOlderRepliesMessages() {
    if (!isRepliesViewing || isLoadingRepliesMessages) return;
    if (repliesOldestOffset <= 0) return;

    isLoadingRepliesMessages = true;
    showTopLoader();

    const anchorEl = messagesContainer.querySelector('.message') || messagesContainer.firstElementChild;
    const anchorTop = anchorEl ? anchorEl.getBoundingClientRect().top : null;

    try {
        const newOffset = Math.max(0, repliesOldestOffset - pageSize);
        const count = repliesOldestOffset - newOffset;
        const data = await fetchRepliesMessages(repliesToMsgId, newOffset, count);
        const batch = Array.isArray(data.messages) ? data.messages : [];
        repliesOldestOffset = Number(data.offset ?? newOffset);
        repliesTotal = Number(data.total ?? repliesTotal);

        if (batch.length > 0) {
            const frag = document.createDocumentFragment();
            for (const m of batch) {
                const idx = (m.msg_id ?? Math.random());
                const el = htmlToElement(createMessageHtml(m, idx, ''));
                if (el) frag.appendChild(el);
            }
            messagesContainer.insertBefore(frag, messagesContainer.firstChild);
        }
    } catch (error) {
        console.error('加载旧 replies 失败:', error);
    } finally {
        isLoadingRepliesMessages = false;
        hideTopLoader();

        if (anchorEl && anchorTop !== null) {
            await new Promise((resolve) => requestAnimationFrame(resolve));
            const newTop = anchorEl.getBoundingClientRect().top;
            window.scrollBy(0, newTop - anchorTop);
            nextTick()
                .then(() => waitForMediaToLoad())
                .then(() => {
                    const topAfterMedia = anchorEl.getBoundingClientRect().top;
                    window.scrollBy(0, topAfterMedia - anchorTop);
                })
                .catch(() => { });
        }
    }
}

function loadOlderRepliesMessagesWithScrollAdjustment() {
    if (isLoadingRepliesMessages) return;
    loadOlderRepliesMessages();
}

function loadMessages() {
    fetchMessages(-pageSize, pageSize)
        .then(data => {
            allMessages = data.messages;
            oldestIndex = data.offset;
            totalMessages = data.total;
            loadInitialMessages();
        })
        .catch(error => {
            console.error('加载聊天记录失败:', error);
        })
        .finally(() => {
            overlay.classList.add('hidden');
        });
}

let currentStartIndex;
let isSearching = false;
let searchQuery = '';
let searchOldestOffset = 0;
let searchTotal = 0;
let isLoadingSearchMessages = false;
const messagesContainer = document.getElementById('messages');

function showTopLoader() {
    if (!topLoader) return;
    topLoader.classList.remove('hidden');
    topLoader.setAttribute('aria-hidden', 'false');
}

function hideTopLoader() {
    if (!topLoader) return;
    topLoader.classList.add('hidden');
    topLoader.setAttribute('aria-hidden', 'true');
}


// 渲染指定区间内的消息，prepend=true 时将消息插入到最前面
function renderMessagesRange(start, end, prepend = false) {
    return new Promise((resolve) => {
        let html = "";
        for (let i = start; i < end; i++) {
            html += createMessageHtml(allMessages[i], i);
        }
        if (prepend) {
            messagesContainer.insertAdjacentHTML('afterbegin', html);
        } else {
            messagesContainer.innerHTML += html;
        }
        resolve();
    });
}

// 初始加载最新的消息
function loadInitialMessages() {
    currentStartIndex = allMessages.length;
    renderMessagesRange(0, currentStartIndex).then(() => {
        setTimeout(async () => {
            await nextTick();
            await waitForMediaToLoad();
            window.scrollTo(0, document.body.scrollHeight);
            requestAnimationFrame(() => window.scrollTo(0, document.body.scrollHeight));
        }, 0);
    });

    function checkAndLoadIfNotScrollable() {
        if (!isSearching && oldestIndex > 0 && document.body.scrollHeight <= window.innerHeight + 100) {
            loadOlderMessagesWithScrollAdjustment();
        }
    }

    // 页面初始化或每次加载完消息后都检查
    checkAndLoadIfNotScrollable();
}

function waitForMediaToLoad() {
    const timeoutMs = 1200;

    // 只等待“已经进入视口附近”的媒体，避免 lazy 图片导致一直等待
    const images = Array.from(document.images)
        .filter(img => !img.complete)
        .filter(img => isInViewport(img))
        .map(img => new Promise(resolve => {
            img.addEventListener('load', resolve, { once: true });
            img.addEventListener('error', resolve, { once: true });
        }));

    const videos = Array.from(document.querySelectorAll('video'))
        .filter(video => video.readyState < 3)
        .filter(video => isInViewport(video))
        .map(video => new Promise(resolve => {
            video.addEventListener('loadeddata', resolve, { once: true });
            video.addEventListener('error', resolve, { once: true });
        }));

    return Promise.race([
        Promise.all([...images, ...videos]),
        new Promise(resolve => setTimeout(resolve, timeoutMs)),
    ]);
}

// 向上加载更多消息
let isLoadingOlderMessages = false;

async function loadOlderMessages() {
    if (oldestIndex <= 0 || isLoadingOlderMessages) return;
    isLoadingOlderMessages = true;
    showTopLoader();

    // Keep viewport anchored to the current first rendered message.
    const anchorEl = messagesContainer.querySelector('.message') || messagesContainer.firstElementChild;
    const anchorTop = anchorEl ? anchorEl.getBoundingClientRect().top : null;
    try {
        let newOffset = Math.max(0, oldestIndex - pageSize);
        let count = oldestIndex - newOffset;
        const data = await fetchMessages(newOffset, count);
        oldestIndex = data.offset;
        allMessages = data.messages.concat(allMessages);
        await renderMessagesRange(0, data.messages.length, true);
        currentStartIndex += data.messages.length;
    } catch (error) {
        console.error('加载旧消息失败:', error);
    } finally {
        isLoadingOlderMessages = false;
        hideTopLoader();

        if (anchorEl && anchorTop !== null) {
            await new Promise((resolve) => requestAnimationFrame(resolve));
            const newTop = anchorEl.getBoundingClientRect().top;
            window.scrollBy(0, newTop - anchorTop);

            // Images are rendered via setTimeout in createMessageHtml; adjust once more after they settle.
            nextTick()
                .then(() => waitForMediaToLoad())
                .then(() => {
                    const topAfterMedia = anchorEl.getBoundingClientRect().top;
                    window.scrollBy(0, topAfterMedia - anchorTop);
                })
                .catch(() => { });
        }
    }
}

function loadOlderMessagesWithScrollAdjustment() {
    if (isLoadingOlderMessages) return;
    loadOlderMessages();
}

async function loadOlderSearchMessages() {
    if (!isSearching || isLoadingSearchMessages) return;
    if (searchOldestOffset <= 0) return;

    isLoadingSearchMessages = true;
    showTopLoader();

    const anchorEl = messagesContainer.querySelector('.message') || messagesContainer.firstElementChild;
    const anchorTop = anchorEl ? anchorEl.getBoundingClientRect().top : null;

    try {
        const newOffset = Math.max(0, searchOldestOffset - pageSize);
        const count = searchOldestOffset - newOffset;
        const data = await fetchSearchMessages(searchQuery, newOffset, count);
        const batch = Array.isArray(data.messages) ? data.messages : [];
        searchOldestOffset = Number(data.offset ?? newOffset);
        searchTotal = Number(data.total ?? searchTotal);

        if (batch.length > 0) {
            const existingFirstMsgEl = messagesContainer.querySelector('.message[data-msg-id]');
            const existingFirstId = existingFirstMsgEl ? Number(existingFirstMsgEl.dataset.msgId) : null;

            const frag = document.createDocumentFragment();
            for (let i = 0; i < batch.length; i++) {
                const m = batch[i];
                const idx = (m.msg_id ?? Math.random());
                const el = htmlToElement(createMessageHtml(m, idx, searchQuery));
                if (el) frag.appendChild(el);

                if (i < batch.length - 1) {
                    const a = Number(batch[i]?.msg_id);
                    const b = Number(batch[i + 1]?.msg_id);
                    if (Number.isFinite(a) && Number.isFinite(b) && b > a + 1) {
                        const gapId = `gap-${++searchGapCounter}`;
                        frag.appendChild(createSeparatorElement(gapId, a, b, 'down', searchQuery));
                        frag.appendChild(createSeparatorElement(gapId, a, b, 'up', searchQuery));
                    }
                }
            }

            const lastId = Number(batch[batch.length - 1]?.msg_id);
            if (Number.isFinite(lastId) && Number.isFinite(existingFirstId) && existingFirstId > lastId + 1) {
                const gapId = `gap-${++searchGapCounter}`;
                frag.appendChild(createSeparatorElement(gapId, lastId, existingFirstId, 'down', searchQuery));
                frag.appendChild(createSeparatorElement(gapId, lastId, existingFirstId, 'up', searchQuery));
            }

            messagesContainer.insertBefore(frag, messagesContainer.firstChild);
        }
    } catch (error) {
        console.error('加载搜索结果失败:', error);
    } finally {
        isLoadingSearchMessages = false;
        hideTopLoader();

        if (anchorEl && anchorTop !== null) {
            await new Promise((resolve) => requestAnimationFrame(resolve));
            const newTop = anchorEl.getBoundingClientRect().top;
            window.scrollBy(0, newTop - anchorTop);

            nextTick()
                .then(() => waitForMediaToLoad())
                .then(() => {
                    const topAfterMedia = anchorEl.getBoundingClientRect().top;
                    window.scrollBy(0, topAfterMedia - anchorTop);
                })
                .catch(() => { });
        }
        updateSearchMoreResultsButton();
    }
}

function loadOlderSearchMessagesWithScrollAdjustment() {
    if (isLoadingSearchMessages) return;
    loadOlderSearchMessages();
}

// 滚动到页面顶部时触发加载更多
let debounceTimer;

function checkScroll() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () {
        if (isRepliesViewing && window.scrollY < 50) {
            loadOlderRepliesMessagesWithScrollAdjustment();
            return;
        }
        if (isRepliesNumSorting && window.scrollY < 50) {
            loadMoreRepliesNumMessages(false);
            return;
        }
        if (isReactionSorting && window.scrollY < 50) {
            loadMoreReactionMessages(false);
            return;
        }
        if (isSearching && window.scrollY < 50) {
            loadOlderSearchMessagesWithScrollAdjustment();
            return;
        }
        if (!isSearching && !isReactionSorting && !isRepliesNumSorting && !isRepliesViewing && window.scrollY < 50 && oldestIndex > 0) {
            loadOlderMessagesWithScrollAdjustment();
        }
    }, 200);
}

window.addEventListener('scroll', checkScroll);

// 搜索函数：分页返回结果（同 get_messages）
function searchMessages() {
    overlay.classList.remove('hidden');
    if (isReactionSorting) {
        const reactionSelect = document.getElementById('reactionSelect');
        if (reactionSelect) reactionSelect.value = '';
        resetReactionSortingState();
    }
    if (isRepliesViewing) {
        resetRepliesViewState();
    }
    const searchValue = document.getElementById('searchBox').value.trim().toLowerCase();
    if (!searchValue) {
        isSearching = false;
        searchQuery = '';
        searchOldestOffset = 0;
        searchTotal = 0;
        isLoadingSearchMessages = false;
        updateSearchMoreResultsButton();
        messagesContainer.innerHTML = "";
        loadMessages();
        overlay.classList.add('hidden');
        return;
    }
    isSearching = true;
    searchQuery = searchValue;
    try {
        fetchSearchMessages(searchQuery, -pageSize, pageSize)
            .then(async (data) => {
                const batch = Array.isArray(data.messages) ? data.messages : [];
                searchOldestOffset = Number(data.offset ?? 0);
                searchTotal = Number(data.total ?? 0);

                messagesContainer.innerHTML = "";
                searchGapCounter = 0;
                const frag = document.createDocumentFragment();
                for (let i = 0; i < batch.length; i++) {
                    const m = batch[i];
                    const idx = (m.msg_id ?? Math.random());
                    const el = htmlToElement(createMessageHtml(m, idx, searchValue));
                    if (el) frag.appendChild(el);

                    if (i < batch.length - 1) {
                        const a = Number(batch[i]?.msg_id);
                        const b = Number(batch[i + 1]?.msg_id);
                        if (Number.isFinite(a) && Number.isFinite(b) && b > a + 1) {
                            const gapId = `gap-${++searchGapCounter}`;
                            frag.appendChild(createSeparatorElement(gapId, a, b, 'down', searchValue));
                            frag.appendChild(createSeparatorElement(gapId, a, b, 'up', searchValue));
                        }
                    }
                }

                // 为“最新一条搜索命中”补一个向下加载（拉取它之后的上下文消息）
                const newestHitId = batch.length ? Number(batch[batch.length - 1]?.msg_id) : null;
                const latestId = await ensureLatestChatMsgId();
                if (Number.isFinite(newestHitId) && Number.isFinite(latestId) && latestId > newestHitId + 1) {
                    const gapId = `gap-${++searchGapCounter}`;
                    frag.appendChild(createSeparatorElement(gapId, newestHitId, latestId + 1, 'down', searchValue));
                }

                messagesContainer.appendChild(frag);

                await nextTick();
                await nextFrame(); // 先让内容渲染出来，避免 loader 卡住直到滚动才消失
                overlay.classList.add('hidden');

                // 让页面滚动到结果底部（更符合“最新消息在底部”的阅读习惯）
                window.scrollTo(0, document.body.scrollHeight);

                // 等待视口附近媒体（有超时，不会因为 lazy 图片卡死）
                await waitForMediaToLoad();

                await ensureSearchScrollable();
            })
            .catch((e) => {
                console.error(e);
                overlay.classList.add('hidden');
            });
    } catch (error) {
        console.error(error);
        overlay.classList.add('hidden');
    }
}

function updateSearchMoreResultsButton() {
    const existing = document.getElementById('searchMoreResults');
    const shouldShow = isSearching && searchOldestOffset > 0 && !isPageScrollable();
    if (!shouldShow) {
        if (existing) existing.remove();
        return;
    }
    if (existing) return;

    const btn = document.createElement('div');
    btn.id = 'searchMoreResults';
    btn.className = 'separator up';
    btn.innerHTML = '<span style=\"color: #aaa; font-size: 0.9rem;\">向上加载更多搜索结果</span>';
    btn.addEventListener('click', () => loadOlderSearchMessagesWithScrollAdjustment());
    messagesContainer.insertBefore(btn, messagesContainer.firstChild);
}

async function ensureSearchScrollable() {
    // 如果搜索结果太少导致没有滚动条，则自动补一些更老的搜索结果，直到可滚动或没有更多
    let guard = 0;
    while (isSearching && searchOldestOffset > 0 && !isPageScrollable() && guard < 5) {
        guard += 1;
        await loadOlderSearchMessages();
        await nextTick();
    }
    updateSearchMoreResultsButton();
}

document.addEventListener('DOMContentLoaded', loadMessages);

const confirmSearchBtn = document.getElementById('confirmSearch');
document.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') {
        confirmSearchBtn.click();
    }
});

// 加载聊天列表到下拉框
function loadChatList() {
    fetch('../chats')
        .then(res => res.json())
        .then(data => {
            const select = document.getElementById('chatSelect');
            data.chats.forEach(chat => {
                const opt = document.createElement('option');
                opt.value = chat.id;
                opt.textContent = chat.remark || chat.id;
                if (chat.id === window.CHAT_ID) {
                    opt.selected = true;
                }
                select.appendChild(opt);
            });
        });
}

document.addEventListener('DOMContentLoaded', loadChatList);

// 切换聊天跳转
document.getElementById('chatSelect').addEventListener('change', function () {
    if (this.value && this.value !== window.CHAT_ID) {
        window.location.href = encodeURIComponent(this.value);
    }
});

function loadReactionEmoticons() {
    const reactionSelect = document.getElementById('reactionSelect');
    if (!reactionSelect) return;

    reactionSelect.innerHTML = '<option value=\"\">按表情排序</option>';
    fetchReactionEmoticons()
        .then(data => {
            const items = Array.isArray(data.emoticons) ? data.emoticons : [];
            items.forEach(item => {
                const emo = item.emoticon;
                if (!emo) return;
                const count = Number(item.count ?? 0);
                const opt = document.createElement('option');
                opt.value = emo;
                opt.textContent = count > 0 ? `${emo} (${count})` : String(emo);
                reactionSelect.appendChild(opt);
            });
        })
        .catch(err => console.error(err));
}

document.addEventListener('DOMContentLoaded', loadReactionEmoticons);

const reactionSelectEl = document.getElementById('reactionSelect');
if (reactionSelectEl) {
    reactionSelectEl.addEventListener('change', function () {
        setReactionSorting(this.value);
    });
}

const repliesNumSelectEl = document.getElementById('repliesNumSelect');
if (repliesNumSelectEl) {
    repliesNumSelectEl.addEventListener('change', function () {
        setRepliesNumSorting(this.value);
    });
}


document.addEventListener('click', (event) => {
    const tile = event.target.closest('.img-tile[data-img-src]');
    if (!tile) return;
    event.preventDefault();
    event.stopPropagation();
    const img = tile.querySelector('img');
    if (img?.classList?.contains('img-broken') && String(tile.dataset?.imgSrc || '').startsWith('/downloads/')) {
        downloadTelegramMediaForTile(tile);
        return;
    }
    openImageViewerFromTile(tile);
});

document.addEventListener('click', (event) => {
    const badge = event.target.closest('.replies-badge[data-reply-to-msg-id]');
    if (!badge) return;
    event.preventDefault();
    event.stopPropagation();
    setRepliesView(badge.dataset.replyToMsgId);
});

document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && isRepliesViewing) {
        exitRepliesView();
    }
});

const exitRepliesBtn = document.getElementById('exitReplies');
if (exitRepliesBtn) {
    exitRepliesBtn.addEventListener('click', () => exitRepliesView());
}

const downloadBrokenBtn = document.getElementById('downloadBrokenImages');
if (downloadBrokenBtn) {
    downloadBrokenBtn.addEventListener('click', () => startDownloadMissingImagesJob(10));
}

// 点击气泡之外的“整行背景”区域：打开 Telegram 对应消息
document.addEventListener('click', (event) => {
    const messageEl = event.target.closest('.message-to-telegram[data-telegram-url]');
    if (!messageEl) return;

    // 只处理点击在整行空白区域（target 即 .message 本身），避免影响文本选择/链接点击等
    if (event.target !== messageEl) return;

    const url = messageEl.dataset.telegramUrl;
    if (!url) return;
    window.open(url, '_blank', 'noopener,noreferrer');
});

// error 事件不冒泡：用捕获阶段统一处理图片加载失败
document.addEventListener('error', (event) => {
    const target = event.target;
    if (!target || target.tagName !== 'IMG') return;
    if (!target.closest('.img-tile') && !target.closest('.image-viewer')) return;
    applyImageFallback(target);
}, true);



