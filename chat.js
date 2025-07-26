// 初始化聊天数据
let allMessages = [];
const overlay = document.getElementById('overlay');
overlay.classList.remove('hidden');
const chatId = window.CHAT_ID;
const pageSize = 20;
const contextSize = 5
let oldestIndex = 0;
let totalMessages = 0;
const DEFAULT_MAX_IMG_HEIGHT = window.innerHeight * 0.5;

// 动态加载 JSON 数据
function fetchMessages(offset, limit) {
    return fetch(`/messages/${chatId}?offset=${offset}&limit=${limit}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('无法加载消息数据');
            }
            return response.json();
        });
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
const messagesContainer = document.getElementById('messages');

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
            reactionsHtml = `<div class="reactions">` +
                r.Results.map(e => `<span>${e.Reaction.Emoticon} ${e.Count}</span>`).join('') +
                `</div>`;
        }
    }
    
    // 2. 回复引用
    if (message.reply_message) {
        const d = message.reply_message;
        let imgPart = '';

        if (d.msg_file_name && /\.(png|jpe?g|gif|webp)$/i.test(d.msg_file_name)) {
            imgPart = `<div class="reply-image">
                   <img src="/${d.msg_file_name}" alt="图片">
                 </div>`;
        } else if (d.msg_files) {
            const files = Array.isArray(d.msg_files)
                ? d.msg_files
                : JSON.parse(d.msg_files);
            imgPart = files.map(fn =>
                /\.(png|jpe?g|gif|webp)$/i.test(fn)
                    ? `<div class="reply-image"><img src="/${fn}" alt="图片"></div>`
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
          <source src="/${message.msg_file_name}" type="video/mp4">
        </video>
      </div>`;
    }
    // 6. 否则，如果是其他文件下载  
    else if (message.msg_file_name) {
        const short = message.msg_file_name.split('/').pop();
        mediaHtml = `
      <div class="download">
        <a href="/${message.msg_file_name}" download>📎 ${short}</a>
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
    <div class="message ${hasImage} ${position} clearfix">
      <div class="user ${position}">${message.user}</div>
      ${replyHtml}
      ${mediaHtml}
      ${message.msg ? `<div class="msg">${messageContent}</div>` : ''}
      ${ogHtml}
      ${reactionsHtml}
      <div class="date ${position}">${message.date}</div>
    </div>`;
}

// 创建可点击的分隔符元素，通过接口按需加载上下文消息
function createSeparatorElement(startIndex, endIndex, direction, searchValue) {
    let separator = document.createElement('div');
    separator.className = 'separator ' + direction;
    if (direction === "up") {
        separator.innerHTML = ' <div style="color: white">.</div><div style="color: white">.</div><div style="color: white">.</div> <span style="color: #aaa; font-size: 0.9rem;">向上加载</span>';
    } else {
        separator.innerHTML = '<span style="color: #aaa; font-size: 0.9rem;">向下加载</span> <div style="color: white">.</div><div style="color: white">.</div><div style="color: white">.</div>';
    }
    separator.dataset.start = startIndex;
    separator.dataset.end = endIndex;
    separator.dataset.direction = direction;
    separator.addEventListener('click', function () {
        let s = parseInt(separator.dataset.start);
        let e = parseInt(separator.dataset.end);
        let dir = separator.dataset.direction;
        let count = Math.min(contextSize, e - s - 1);
        let offset = dir === "down" ? s + 1 : e - count;
        let parent = separator.parentNode;
        let nextSibling = separator.nextSibling;
        let prevSibling = separator.previousElementSibling;
        fetchMessages(offset, count).then(data => {
            let html = "";
            data.messages.forEach((m, idx) => {
                let messageHtml = createMessageHtml(m, offset + idx, searchValue);
                messageHtml = messageHtml.replace('class="message', 'class="message context');
                html += messageHtml;
            });
            parent.removeChild(separator);
            let container = document.createElement('div');
            container.innerHTML = html;
            const firstChild = container.firstChild;
            while (container.firstChild) {
                parent.insertBefore(container.firstChild, nextSibling);
            }
            if (dir === "down") {
                if (s + count < e - 1) {
                    let newSep = createSeparatorElement(s + count, e, "down", searchValue);
                    parent.insertBefore(newSep, nextSibling);
                } else if (nextSibling) {
                    parent.removeChild(nextSibling);
                }
            } else {
                if (s + count < e - 1) {
                    let newSep = createSeparatorElement(s, e - count, "up", searchValue);
                    parent.insertBefore(newSep, firstChild);
                } else if (prevSibling) {
                    parent.removeChild(prevSibling);
                }
            }
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
        waitForMediaToLoad().then(() => {
            window.scrollTo(0, document.body.scrollHeight);
        });
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
    // 获取所有图片和视频
    const images = Array.from(document.images).map(img => {
        if (img.complete) return Promise.resolve();
        return new Promise(resolve => {
            img.addEventListener('load', resolve, {once: true});
            img.addEventListener('error', resolve, {once: true});
        });
    });

    const videos = Array.from(document.querySelectorAll('video')).map(video => {
        // readyState >= 3 表示可以播放（已加载足够数据）
        if (video.readyState >= 3) return Promise.resolve();
        return new Promise(resolve => {
            video.addEventListener('loadeddata', resolve, {once: true});
            video.addEventListener('error', resolve, {once: true});
        });
    });
    return Promise.all([...images, ...videos]);
}

// 向上加载更多消息
let isLoadingOlderMessages = false;

async function loadOlderMessages() {
    if (oldestIndex <= 0 || isLoadingOlderMessages) return;
    isLoadingOlderMessages = true;
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
    }
}

function loadOlderMessagesWithScrollAdjustment() {
    if (isLoadingOlderMessages) return;
    loadOlderMessages();
}

// 当非搜索模式下，滚动到页面顶部时触发加载更多
let debounceTimer;

function checkScroll() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () {
        if (!isSearching && window.scrollY < 50 && oldestIndex > 0) {
            loadOlderMessagesWithScrollAdjustment();
        }
    }, 200);
}

window.addEventListener('scroll', checkScroll);

// 搜索函数，服务器返回匹配消息及其索引，非连续组之间插入加载按钮
function searchMessages() {
    overlay.classList.remove('hidden');
    const searchValue = document.getElementById('searchBox').value.trim().toLowerCase();
    if (!searchValue) {
        isSearching = false;
        messagesContainer.innerHTML = "";
        loadInitialMessages();
        overlay.classList.add('hidden');
        return;
    }
    isSearching = true;
    try {
        fetch(`/search/${chatId}?q=${encodeURIComponent(searchValue)}`)
            .then(response => response.json())
            .then(data => {
                const results = data.results;
                messagesContainer.innerHTML = "";
                let fragment = document.createDocumentFragment();
                if (results.length > 0 && results[0].index > 0) {
                    fragment.appendChild(createSeparatorElement(0, results[0].index, "up", searchValue));
                }
                let lastIndex = null;
                results.forEach(r => {
                    const idx = r.index;
                    if (lastIndex !== null && idx !== lastIndex + 1) {
                        fragment.appendChild(createSeparatorElement(lastIndex, idx, "down", searchValue));
                        fragment.appendChild(createSeparatorElement(lastIndex, idx, "up", searchValue));
                    }
                    let tempDiv = document.createElement('div');
                    tempDiv.innerHTML = createMessageHtml(r, idx, searchValue);
                    fragment.appendChild(tempDiv.firstElementChild);
                    lastIndex = idx;
                });
                if (lastIndex !== null && lastIndex < totalMessages - 1) {
                    fragment.appendChild(createSeparatorElement(lastIndex, totalMessages, "down", searchValue));
                }
                messagesContainer.appendChild(fragment);
                overlay.classList.add('hidden');
            });
    } catch (error) {
        console.error(error);
        overlay.classList.add('hidden');
    }
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
    fetch('/chats')
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
        window.location.href = '/chat/' + encodeURIComponent(this.value);
    }
});
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

        if (scale === maxHeight / img.height) {
            const image_bg = document.createElement('img');
            image_bg.src = img.url.startsWith('http') ? img.url : `/${img.url}`;
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
        image.src          = img.url.startsWith('http') ? img.url : `/${img.url}`;
        image.alt          = '图片';
        image.style.width  = `${w}px`;
        image.style.height = `${h}px`;
        image.style.objectFit   = 'cover';
        // if (options.hasReaction) {
        //     image.style.marginTop = '0.4rem';
        // } 

        // 包裹 <a> 链接
        const link = document.createElement('a');
        link.href   = `/${img.url}`;
        link.target = '_blank';
        link.style.zIndex = '1';
        link.appendChild(image);

        containerEl.appendChild(link);
    });
}



