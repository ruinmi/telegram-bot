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
        <button type="button" class="image-viewer__close" data-action="close" aria-label="关闭">×</button>
        <a class="image-viewer__download" data-role="download" download target="_blank" rel="noopener">下载</a>
        <img class="image-viewer__img" data-role="img" alt="图片预览" />
      </div>
    `;
    document.body.appendChild(root);

    const img = root.querySelector('[data-role="img"]');
    img.addEventListener('error', () => applyImageFallback(img));

    const close = () => {
        root.classList.add('hidden');
        document.body.classList.remove('no-scroll');
    };

    root.addEventListener('click', (e) => {
        const action = e.target?.dataset?.action;
        if (action === 'close') close();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !root.classList.contains('hidden')) close();
    });

    _imageViewer = {
        root,
        img,
        close,
        downloadLink: root.querySelector('[data-role="download"]'),
    };
    return _imageViewer;
}

function openImageViewer(url) {
    const src = resolveMediaUrl(url);
    if (!src) return;
    const viewer = ensureImageViewer();
    viewer.img.dataset.fallbackApplied = '0';
    viewer.img.classList.remove('img-broken');
    viewer.img.src = src;
    viewer.downloadLink.href = src;
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

function resetReactionSortingState() {
    isReactionSorting = false;
    reactionEmoticon = '';
    reactionOffset = 0;
    reactionTotal = 0;
    isLoadingReactionMessages = false;
}

function setReactionSorting(emoticon) {
    const picked = (emoticon || '').trim();
    if (!picked) {
        resetReactionSortingState();
        messagesContainer.innerHTML = '';
        loadMessages();
        return;
    }

    isSearching = false;
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
        if (isReactionSorting && window.scrollY < 50) {
            loadMoreReactionMessages(false);
            return;
        }
        if (isSearching && window.scrollY < 50) {
            loadOlderSearchMessagesWithScrollAdjustment();
            return;
        }
        if (!isSearching && !isReactionSorting && window.scrollY < 50 && oldestIndex > 0) {
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
                if (chat.id === window.CHAT_ID) opt.selected = true;
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


document.addEventListener('click', (event) => {
    const tile = event.target.closest('.img-tile[data-img-src]');
    if (!tile) return;
    event.preventDefault();
    event.stopPropagation();
    openImageViewer(tile.dataset.imgSrc);
});

// error 事件不冒泡：用捕获阶段统一处理图片加载失败
document.addEventListener('error', (event) => {
    const target = event.target;
    if (!target || target.tagName !== 'IMG') return;
    if (!target.closest('.img-tile') && !target.closest('.image-viewer')) return;
    applyImageFallback(target);
}, true);



