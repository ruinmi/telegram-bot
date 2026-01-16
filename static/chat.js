// 初始化聊天数据
let allMessages = [];
const overlay = document.getElementById('overlay');
overlay.classList.remove('hidden');
const topLoader = document.getElementById('topLoader');
const chatId = window.CHAT_ID;
const pageSize = 20;
const contextSize = 5
let searchGapCounter = 0;
let latestChatMsgId = null;
let oldestIndex = 0;
let totalMessages = 0;
const DEFAULT_MAX_IMG_HEIGHT = window.innerHeight * 0.5;

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

function resolveMediaUrl(url) {
    const raw = (url || '').trim();
    if (!raw) return '';
    if (/^https?:\/\//i.test(raw)) return raw;

    let cleaned = raw;
    while (cleaned.startsWith('../')) cleaned = cleaned.slice(3);
    if (cleaned.startsWith('./')) cleaned = cleaned.slice(2);

    if (cleaned.startsWith('/')) return cleaned;
    return `/${cleaned}`;
}

const BROKEN_IMAGE_PLACEHOLDER = (() => {
    const svg = `
<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#2b2b2b"/>
      <stop offset="1" stop-color="#151515"/>
    </linearGradient>
  </defs>
  <rect width="640" height="480" fill="url(#g)"/>
  <rect x="32" y="32" width="576" height="416" rx="28" fill="none" stroke="#ffffff2b" stroke-width="4"/>
  <g transform="translate(0,8)" fill="none" stroke="#ffffffb0" stroke-width="10" stroke-linecap="round" stroke-linejoin="round">
    <rect x="220" y="170" width="200" height="160" rx="18" stroke="#ffffff66"/>
    <path d="M260 310h120" stroke="#ffffff66"/>
  </g>
  <text x="320" y="390" text-anchor="middle" font-family="Segoe UI, PingFang SC, Microsoft YaHei, sans-serif" font-size="22" fill="#ffffffb0">
    图片加载失败
  </text>
</svg>`.trim();
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
})();

function applyImageFallback(imgEl) {
    if (!imgEl) return;
    if (imgEl.dataset.fallbackApplied === '1') return;
    imgEl.dataset.fallbackApplied = '1';
    imgEl.classList.add('img-broken');
    imgEl.src = BROKEN_IMAGE_PLACEHOLDER;
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

function fetchMessagesBetweenMsgIds(startMsgId, endMsgId, direction, limit) {
    return fetch(
        `../messages_between/${chatId}?start_msg_id=${startMsgId}&end_msg_id=${endMsgId}&direction=${encodeURIComponent(direction)}&limit=${limit}`
    ).then(response => {
        if (!response.ok) {
            throw new Error('无法加载上下文消息');
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

function highlightText(text, searchValue) {
    if (!searchValue) return text;

    // 提取URL，并用占位符替换
    const urlRegex = /(https?:\/\/[^\s]+)/g;

    const placeholders = [];
    text = text.replace(urlRegex, (match) => {
        const index = placeholders.length;
        placeholders.push(match);
        return `__URL_PLACEHOLDER_${index}__`;
    });

    // 分割关键词（支持多个关键词）
    const keywords = searchValue
        .trim()
        .split(/\s+/) // 按多个空格、Tab分隔
        .filter(Boolean)
        .map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')); // 转义正则特殊字符

    if (keywords.length > 0) {
        const regex = new RegExp(`(${keywords.join('|')})`, 'gi');
        text = text.replace(regex, '<span class="highlight">$1</span>');
    }

    // 恢复URL占位符，并根据searchValue判断是否需要高亮整个URL
    placeholders.forEach((url, index) => {
        const shouldHighlight = keywords.some(keyword =>
            url.toLowerCase().includes(keyword.toLowerCase())
        );
        const replacement = shouldHighlight
            ? `<span class="highlight">${url}</span>`
            : url;
        text = text.replace(`__URL_PLACEHOLDER_${index}__`, replacement);
    });

    return text;
}

// 根据单个消息数据生成 HTML 结构
function createMessageHtml(message, index, searchValue) {
    const position = message.user === '我' ? 'right' : 'left';

    // 1. 文本内容
    let messageContent = message.msg
        ? highlightText(message.msg, searchValue)
        : '';
    messageContent = messageContent
        .replace(/(https?:\/\/\S+)/g, '<a href="$1" target="_blank">$1</a>')
        .replace(/\n/g, '<br/>');

    // 占位变量
    let replyHtml     = '';
    let mediaHtml     = '';
    let ogHtml        = '';
    let reactionsHtml = '';

    let hasReaction = false;
    if (message.reactions) {
        const r = typeof message.reactions === 'string'
            ? JSON.parse(message.reactions)
            : message.reactions;
        if (r.Results?.length) {
            hasReaction = true;
            const sortedResults = [...r.Results].sort((a, b) => {
                const countA = Number(a?.Count ?? 0);
                const countB = Number(b?.Count ?? 0);
                if (countA !== countB) return countB - countA;
                const emoA = String(a?.Reaction?.Emoticon ?? '');
                const emoB = String(b?.Reaction?.Emoticon ?? '');
                return emoA.localeCompare(emoB);
            });
            reactionsHtml = `<div class="reactions">` +
                sortedResults.map(e => `<span>${e.Reaction.Emoticon} ${e.Count}</span>`).join('') +
                `</div>`;
        }
    }
    
    // 2. 回复引用
    if (message.reply_message) {
        const d = message.reply_message;
        let imgPart = '';

        if (d.msg_file_name && /\.(png|jpe?g|gif|webp)$/i.test(d.msg_file_name)) {
            const src = resolveMediaUrl(d.msg_file_name);
            imgPart = `<div class="reply-image">
                   <div class="img-tile reply-image__btn" data-img-src="${src}">
                     <img src="${src}" alt="图片" loading="lazy">
                   </div>
                 </div>`;
        } else if (d.msg_files) {
            const files = Array.isArray(d.msg_files)
                ? d.msg_files
                : JSON.parse(d.msg_files);
            imgPart = files.map(fn =>
                /\.(png|jpe?g|gif|webp)$/i.test(fn)
                    ? `<div class="reply-image"><div class="img-tile reply-image__btn" data-img-src="${resolveMediaUrl(fn)}"><img src="${resolveMediaUrl(fn)}" alt="图片" loading="lazy"></div></div>`
                    : ''
            ).join('');
        }

        let replyText = d.msg ? highlightText(d.msg, searchValue) : '';
        replyText = replyText
            .replace(/(https?:\/\/\S+)/g, '<a href="$1" target="_blank">$1</a>')
            .replace(/\n/g, '<br/>');

        replyHtml = `
      <div class="reply-info">
        <div class="reply-content ${position}">
          ${imgPart}
          <div class="reply-text">${replyText}</div>
        </div>
      </div>`;
    }

    let hasImage = '';
    // 3. 收集所有“普通图片”文件  
    const imageFiles = [];
    if (message.msg_file_name && /\.(png|jpe?g|gif|webp)$/i.test(message.msg_file_name)) {
        imageFiles.push(message.msg_file_name);
    }
    if (message.msg_files) {
        const files = Array.isArray(message.msg_files)
            ? message.msg_files
            : JSON.parse(message.msg_files);
        files.forEach(fn => {
            if (/\.(png|jpe?g|gif|webp)$/i.test(fn)) {
                imageFiles.push(fn);
            }
        });

        hasImage = 'has-image';
    }
    
    // 4. 如果有图片 —— 统一走 renderImagesInBubble  
    if (imageFiles.length > 0) {
        hasImage = 'has-image';
        const cid = `img-container-${index}`;
        mediaHtml = `<div id="${cid}" class="image-grid"></div>`;

        setTimeout(() => {
            const c = document.getElementById(cid);
            if (!c) return;
            const list = imageFiles.map(fn => ({
                url:    fn,
                width:  message.ori_width  || 400,
                height: message.ori_height || 300
            }));
            renderImagesInBubble(c, list, {
                maxPerRow: 3,
                gap:       1,
                maxHeight: DEFAULT_MAX_IMG_HEIGHT,
                hasReaction: hasReaction,
            });
        }, 0);
    }
    // 5. 否则，如果是视频  
    else if (message.msg_file_name && /\.(mp4|mov|avi)$/i.test(message.msg_file_name)) {
        mediaHtml = `
      <div class="video">
        <video controls style="max-width:100%;border-radius:6px;">
          <source src="${resolveMediaUrl(message.msg_file_name)}" type="video/mp4">
        </video>
      </div>`;
    }
    // 6. 否则，如果是其他文件下载  
    else if (message.msg_file_name) {
        const short = message.msg_file_name.split('/').pop();
        mediaHtml = `
      <div class="download">
        <a href="${resolveMediaUrl(message.msg_file_name)}" download>📎 ${short}</a>
      </div>`;
    }

    // 7. OG 预览 —— 也走 renderImagesInBubble（单图，不包链接）
    if (message.og_info && message.og_info.image) {
        hasImage = 'has-image';
        const cidOg = `og-img-${index}`;
        const oriW  = message.ori_width  || 400;
        const oriH  = message.ori_height || 300;

        ogHtml = `
      <a class="og-info" href="${message.og_info.url}" target="_blank">
        <div class="og-content">
          ${message.og_info.site_name
            ? `<div class="og-sitename">${message.og_info.site_name}</div>`
            : ''}
          ${message.og_info.description
            ? `<div class="og-text">${message.og_info.description}</div>`
            : message.og_info.title
                ? `<div class="og-text">${message.og_info.title}</div>`
                : ''}
          <div class="og-image">
            <div id="${cidOg}" class="image-grid"></div>
          </div>
        </div>
      </a>`;

        setTimeout(() => {
            const c = document.getElementById(cidOg);
            if (!c) return;
            renderImagesInBubble(c, [{
                url:    message.og_info.image,
                width:  oriW,
                height: oriH
            }], {
                wrapLink: false,
                maxHeight: DEFAULT_MAX_IMG_HEIGHT,
                hasReaction: hasReaction,
            });
        }, 0);
    }

    if (!message.msg) {
        hasImage = '';
    } 

    // 6. 拼接整体
    return `
    <div class="message ${hasImage} ${position} clearfix" data-msg-id="${message.msg_id ?? ''}">
      <div class="user ${position}">${message.user}</div>
      ${replyHtml}
      ${mediaHtml}
      ${message.msg ? `<div class="msg">${messageContent}</div>` : ''}
      ${ogHtml}
      ${reactionsHtml}
      <div class="date ${position}">${message.date}</div>
    </div>`;
}

function htmlToElement(html) {
    const tpl = document.createElement('template');
    tpl.innerHTML = (html || '').trim();
    return tpl.content.firstElementChild;
}

// 创建可点击的分隔符元素，通过接口按需加载上下文消息（按 msg_id 取区间）
function createSeparatorElement(gapId, startMsgId, endMsgId, direction, searchValue) {
    let separator = document.createElement('div');
    separator.className = 'separator ' + direction;
    separator.dataset.gapId = String(gapId);
    separator.dataset.startMsgId = String(startMsgId);
    separator.dataset.endMsgId = String(endMsgId);
    separator.dataset.direction = direction;
    if (direction === "up") {
        separator.innerHTML = ' <div style="color: white">.</div><div style="color: white">.</div><div style="color: white">.</div> <span style="color: #aaa; font-size: 0.9rem;">向上加载</span>';
    } else {
        separator.innerHTML = '<span style="color: #aaa; font-size: 0.9rem;">向下加载</span> <div style="color: white">.</div><div style="color: white">.</div><div style="color: white">.</div>';
    }
    separator.addEventListener('click', function () {
        let s = parseInt(separator.dataset.startMsgId);
        let e = parseInt(separator.dataset.endMsgId);
        let dir = separator.dataset.direction;
        const gap = separator.dataset.gapId;
        let parent = separator.parentNode;
        let nextSibling = separator.nextSibling;

        fetchMessagesBetweenMsgIds(s, e, dir, contextSize).then(data => {
            const batch = Array.isArray(data.messages) ? data.messages : [];
            const hasMore = Boolean(data.has_more);

            if (!batch.length) {
                const otherDir = dir === 'down' ? 'up' : 'down';
                const other = parent.querySelector(`.separator[data-gap-id="${gap}"][data-direction="${otherDir}"]`);
                parent.removeChild(separator);
                if (other) other.remove();
                return;
            }

            parent.removeChild(separator);

            const fragment = document.createDocumentFragment();
            let firstInserted = null;
            for (const m of batch) {
                const idx = (m.msg_id ?? Math.random());
                let messageHtml = createMessageHtml(m, idx, searchValue);
                messageHtml = messageHtml.replace('class="message', 'class="message context');
                const el = htmlToElement(messageHtml);
                if (!el) continue;
                if (!firstInserted) firstInserted = el;
                fragment.appendChild(el);
            }
            parent.insertBefore(fragment, nextSibling);

            const firstId = Number(batch[0]?.msg_id);
            const lastId = Number(batch[batch.length - 1]?.msg_id);
            const downSep = parent.querySelector(`.separator[data-gap-id="${gap}"][data-direction="down"]`);
            const upSep = parent.querySelector(`.separator[data-gap-id="${gap}"][data-direction="up"]`);

            if (dir === "down") {
                if (upSep && Number.isFinite(lastId)) upSep.dataset.startMsgId = String(lastId);
                if (hasMore && Number.isFinite(lastId)) {
                    const newSep = createSeparatorElement(gap, lastId, e, "down", searchValue);
                    parent.insertBefore(newSep, nextSibling);
                } else {
                    if (upSep) upSep.remove();
                }
            } else {
                if (downSep && Number.isFinite(firstId)) downSep.dataset.endMsgId = String(firstId);
                if (hasMore && Number.isFinite(firstId) && firstInserted) {
                    const newSep = createSeparatorElement(gap, s, firstId, "up", searchValue);
                    parent.insertBefore(newSep, firstInserted);
                } else {
                    if (downSep) downSep.remove();
                }
            }
        }).catch(err => {
            console.error('加载上下文消息失败:', err);
        });
    });
    return separator;
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

    reactionSelect.innerHTML = '<option value=\"\">按表情(Reaction)排序</option>';
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
/**
 * 计算单张图片最大宽度(px)，基于「气泡」的内容区宽度
 */
function calculateMaxImageWidth(containerEl, imagesPerRow = 3, gap = 6) {
    // 找到最近的气泡容器
    const bubbleEl = containerEl.closest('.message');
    const bubbleStyle = window.getComputedStyle(bubbleEl);

    // 气泡内容区真实可用宽度 = clientWidth – 内边距
    const bubbleInnerWidth = bubbleEl.clientWidth
        - parseFloat(bubbleStyle.paddingLeft)
        - parseFloat(bubbleStyle.paddingRight);

    // 每张图可用宽度 = (可用宽 – 间距总和) / 张数
    return Math.floor(
        (bubbleInnerWidth - gap * (imagesPerRow - 1))
        / imagesPerRow
    );
}


/**
 * 在 containerEl 容器里等比渲染 imageList，
 * 并尽量铺满父级气泡的可用宽度
 */
function renderImagesInBubble(containerEl, imageList, options = {}) {
    // 如果只有一张，默认一行一张
    const imagesPerRow = imageList.length === 1
        ? 1
        : (options.maxPerRow || 3);

    const gap = imageList.length === 1
        ? 0
        : (options.gap || 1);

    // 计算最大宽高
    const maxWidth  = calculateMaxImageWidth(containerEl, imagesPerRow, gap);
    const maxHeight = options.maxHeight || maxWidth;

    // 强制容器铺满气泡宽度
    containerEl.style.display  = 'flex';
    containerEl.style.flexWrap = 'wrap';
    containerEl.style.gap      = `${gap}px`;
    containerEl.style.width    = '100%';      // 全宽
    containerEl.style.boxSizing= 'border-box';

    imageList.forEach(img => {
        const scale = Math.min(maxWidth / img.width, maxHeight / img.height);
        const w = Math.round(img.width * scale);
        const h = Math.round(img.height * scale);
        const src = resolveMediaUrl(img.url);

        if (scale === maxHeight / img.height) {
            const image_bg = document.createElement('img');
            image_bg.src = src;
            image_bg.alt = '图片';
            image_bg.style.width = `100%`;
            image_bg.style.height = `100%`;
            image_bg.style.position = 'absolute';
            image_bg.style.filter = 'blur(15px)';
            image_bg.style.userSelect = 'none';
            image_bg.style.pointerEvents = 'none';
            containerEl.appendChild(image_bg);
        }

        const image = document.createElement('img');
        image.src = src;
        image.alt          = '图片';
        image.style.width  = `${w}px`;
        image.style.height = `${h}px`;
        image.style.objectFit   = 'cover';
        image.loading = 'lazy';
        image.addEventListener('error', () => applyImageFallback(image), { once: true });
        // if (options.hasReaction) {
        //     image.style.marginTop = '0.4rem';
        // } 

        const tile = document.createElement('div');
        tile.className = 'img-tile';
        tile.dataset.imgSrc = src;
        tile.style.zIndex = '1';
        tile.style.width = `${w}px`;
        tile.style.height = `${h}px`;
        tile.appendChild(image);
        containerEl.appendChild(tile);
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



