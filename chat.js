        // 初始化聊天数据
        let allMessages = [];
        const overlay = document.getElementById('overlay');
        overlay.classList.remove('hidden');
        const chatId = window.CHAT_ID;
        const pageSize = 20;
        const contextSize = 5
        let oldestIndex = 0;
        let totalMessages = 0;
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
            let position = message.user === '我' ? 'right' : 'left';
            let messageContent = message.msg ? highlightText(message.msg, searchValue) : "";
            messageContent = messageContent.replace(/(https?:\/\/\S+)/g, '<a href="$1" target="_blank">$1</a>');
            messageContent = messageContent.replace(/\n/g, "<br/>");
            let mediaHtml = "";
            let ogHtml = "";
            let replyHtml = "";
            let reactionsHtml = "";
            if (message.reply_message) {
                const data = message.reply_message;
                let img = "";
                if (data.msg_file_name) {
                    const lower = data.msg_file_name.toLowerCase();
                    if (/(?:\.png|\.jpg|\.jpeg|\.gif|\.webp)$/.test(lower)) {
                        img = `<div class="reply-image"><img src="/${data.msg_file_name}" alt="图片"></div>`;
                    }
                } else if (data.msg_files) {
                    let files = Array.isArray(data.msg_files) ? data.msg_files : JSON.parse(data.msg_files);
                    if (files) {
                        img = files.map(fileName => {
                            let lowerName = fileName.toLowerCase();
                            if (lowerName.endsWith('.png') || lowerName.endsWith('.jpg') || lowerName.endsWith('.jpeg') || lowerName.endsWith('.gif') || lowerName.endsWith('.webp')) {
                                return `<div class="reply-image"><img src="/${fileName}" alt="图片"></div>`;
                            }
                        }).join('');
                    }
                }
                let text = data.msg ? highlightText(data.msg, searchValue) : "";
                text = text.replace(/(https?:\/\/\S+)/g, '<a href="$1" target="_blank">$1</a>');
                text = text.replace(/\n/g, '<br/>');
                replyHtml = `<div class="reply-info"><div class="reply-content ${position}">${img}<div class="reply-text">${text}</div></div></div>`;
            }
            
            if (message.msg_file_name) {
                let lowerName = message.msg_file_name.toLowerCase();
                if (lowerName.endsWith('.png') || lowerName.endsWith('.jpg') || lowerName.endsWith('.jpeg') || lowerName.endsWith('.gif') || lowerName.endsWith('.webp')) {
                    mediaHtml = `<div class="image"><img style="max-width: ${message.display_width}px" src="/${message.msg_file_name}" alt="图片" /></div>`;
                } else if (lowerName.endsWith('.mp4') || lowerName.endsWith('.mov') || lowerName.endsWith('.avi')) {
                    mediaHtml = `<div class="video"><video controls><source src="/${message.msg_file_name}" type="video/mp4">Your browser does not support the video tag.</video></div>`;
                } else {
                    let parts = message.msg_file_name.split('/');
                    let fileName = parts[parts.length - 1];
                    mediaHtml = `
                            <div class="download">
                                <a href="/${message.msg_file_name}" download>
                                    <svg style="vertical-align: bottom;" t="1739785072303" class="icon" viewBox="0 0 1024 1024" version="1.1" xmlns="http://www.w3.org/2000/svg" p-id="1483" width="24" height="24"><path d="M928 448c-17.7 0-32 14.3-32 32v319.5c0 17.9-14.6 32.5-32.5 32.5h-703c-17.9 0-32.5-14.6-32.5-32.5V480c0-17.7-14.3-32-32-32s-32 14.3-32 32v319.5c0 53.2 43.3 96.5 96.5 96.5h703c53.2 0 96.5-43.3 96.5-96.5V480c0-17.7-14.3-32-32-32z" fill="#fff" p-id="1484"></path><path d="M489.4 726.6c0.4 0.4 0.8 0.7 1.2 1.1l0.4 0.4c0.2 0.2 0.5 0.4 0.7 0.6 0.2 0.2 0.4 0.3 0.6 0.4 0.2 0.2 0.5 0.4 0.7 0.5 0.2 0.1 0.4 0.3 0.6 0.4 0.2 0.2 0.5 0.3 0.7 0.5 0.2 0.1 0.4 0.2 0.6 0.4 0.3 0.2 0.5 0.3 0.8 0.5 0.2 0.1 0.3 0.2 0.5 0.3 0.3 0.2 0.6 0.3 0.9 0.5 0.1 0.1 0.3 0.1 0.4 0.2 0.3 0.2 0.7 0.3 1 0.5 0.1 0.1 0.2 0.1 0.3 0.2 0.4 0.2 0.7 0.3 1.1 0.5 0.1 0 0.2 0.1 0.2 0.1 0.4 0.2 0.8 0.3 1.2 0.5 0.1 0 0.1 0 0.2 0.1 0.4 0.2 0.9 0.3 1.3 0.4h0.1c0.5 0.1 0.9 0.3 1.4 0.4h0.1c0.5 0.1 0.9 0.2 1.4 0.3h0.2c0.4 0.1 0.9 0.2 1.3 0.2h0.4c0.4 0.1 0.8 0.1 1.2 0.1 0.3 0 0.5 0 0.8 0.1 0.3 0 0.5 0 0.8 0.1H512.2c0.7 0 1.3 0 1.9-0.1h0.6c0.6 0 1.2-0.1 1.8-0.2h0.3c0.7-0.1 1.4-0.2 2.1-0.4 0.1 0 0.2 0 0.3-0.1 0.7-0.2 1.3-0.3 2-0.5h0.1c0.7-0.2 1.4-0.5 2.1-0.7h0.1l2.1-0.9h0.1c0.7-0.3 1.4-0.7 2-1.1 0.1 0 0.1-0.1 0.2-0.1 1.6-0.9 3.2-2 4.6-3.2 0.2-0.2 0.4-0.4 0.6-0.5 0.2-0.2 0.4-0.3 0.6-0.5 0.2-0.2 0.5-0.4 0.7-0.7l0.4-0.4c0.1-0.1 0.2-0.1 0.2-0.2l191.7-191.7c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0L544 626.7V96c0-17.7-14.3-32-32-32s-32 14.3-32 32v530.7L342.6 489.4c-12.5-12.5-32.8-12.5-45.3 0s-12.5 32.8 0 45.3l192.1 191.9z" fill="#fff" p-id="1485"></path></svg>
                                    ${fileName}
                                </a>
                            </div>`;
                }
            } else if (message.og_info && message.og_info.image) {
                ogHtml = `
                    <a class="og-info" href="${message.og_info.url}" target="_blank">
                        <div class="og-content">
                            ${message.og_info.site_name ? `<div class="og-sitename">${message.og_info.site_name}</div>` : ""}
                            ${message.og_info.description ? `<div class="og-text">${message.og_info.description}</div>` : message.og_info.title ? `<div class="og-text">${message.og_info.title}</div>` : ""}
                            <div class="og-image">
                                <img src="${message.og_info.image}" 
                                    alt="${message.og_info.title || 'Open Graph Image'}" 
                                    />
                            </div>
                        </div>
                    </a>`;
            } else if (message.msg_files) {
                let files;
                if (!Array.isArray(message.msg_files)) {
                    files = JSON.parse(message.msg_files);
                } else {
                    files = message.msg_files;
                }
            if (files) {
                let innerHtml = files.map(fileName => {
                        let lowerName = fileName.toLowerCase();
                        if (lowerName.endsWith('.png') || lowerName.endsWith('.jpg') || lowerName.endsWith('.jpeg') || lowerName.endsWith('.gif') || lowerName.endsWith('.webp')) {
                            return `
        <div class="image">
            <a href="/${fileName}" target="_blank">
                <img style="max-width: ${message.display_width}px" src="/${fileName}" alt="图片" />
            </a>
        </div>
    `;
                        } else if (lowerName.endsWith('.mp4') || lowerName.endsWith('.mov') || lowerName.endsWith('.avi')) {
                            return `<div class="video"><video controls><source src="/${fileName}" type="video/mp4">Your browser does not support the video tag.</video></div>`;
                        } else {
                            let parts = fileName.split('/');
                            let shortName = parts[parts.length - 1];
                            return `
                    <div class="download">
                        <a href="/${fileName}" download>
                            <svg style="vertical-align: bottom;" t="1739785072303" class="icon" viewBox="0 0 1024 1024" version="1.1" xmlns="http://www.w3.org/2000/svg" p-id="1483" width="24" height="24"><path d="M928 448c-17.7 0-32 14.3-32 32v319.5c0 17.9-14.6 32.5-32.5 32.5h-703c-17.9 0-32.5-14.6-32.5-32.5V480c0-17.7-14.3-32-32-32s-32 14.3-32 32v319.5c0 53.2 43.3 96.5 96.5 96.5h703c53.2 0 96.5-43.3 96.5-96.5V480c0-17.7-14.3-32-32-32z" fill="#fff" p-id="1484"></path><path d="M489.4 726.6c0.4 0.4 0.8 0.7 1.2 1.1l0.4 0.4c0.2 0.2 0.5 0.4 0.7 0.6 0.2 0.2 0.4 0.3 0.6 0.4 0.2 0.2 0.5 0.4 0.7 0.5 0.2 0.1 0.4 0.3 0.6 0.4 0.2 0.2 0.5 0.3 0.7 0.5 0.2 0.1 0.4 0.2 0.6 0.4 0.3 0.2 0.5 0.3 0.8 0.5 0.2 0.1 0.3 0.2 0.5 0.3 0.3 0.2 0.6 0.3 0.9 0.5 0.1 0.1 0.3 0.1 0.4 0.2 0.3 0.2 0.7 0.3 1 0.5 0.1 0.1 0.2 0.1 0.3 0.2 0.4 0.2 0.7 0.3 1.1 0.5 0.1 0 0.2 0.1 0.2 0.1 0.4 0.2 0.8 0.3 1.2 0.5 0.1 0 0.1 0 0.2 0.1 0.4 0.2 0.9 0.3 1.3 0.4h0.1c0.5 0.1 0.9 0.3 1.4 0.4h0.1c0.5 0.1 0.9 0.2 1.4 0.3h0.2c0.4 0.1 0.9 0.2 1.3 0.2h0.4c0.4 0.1 0.8 0.1 1.2 0.1 0.3 0 0.5 0 0.8 0.1 0.3 0 0.5 0 0.8 0.1H512.2c0.7 0 1.3 0 1.9-0.1h0.6c0.6 0 1.2-0.1 1.8-0.2h0.3c0.7-0.1 1.4-0.2 2.1-0.4 0.1 0 0.2 0 0.3-0.1 0.7-0.2 1.3-0.3 2-0.5h0.1c0.7-0.2 1.4-0.5 2.1-0.7h0.1l2.1-0.9h0.1c0.7-0.3 1.4-0.7 2-1.1 0.1 0 0.1-0.1 0.2-0.1 1.6-0.9 3.2-2 4.6-3.2 0.2-0.2 0.4-0.4 0.6-0.5 0.2-0.2 0.4-0.3 0.6-0.5 0.2-0.2 0.5-0.4 0.7-0.7l0.4-0.4c0.1-0.1 0.2-0.1 0.2-0.2l191.7-191.7c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0L544 626.7V96c0-17.7-14.3-32-32-32s-32 14.3-32 32v530.7L342.6 489.4c-12.5-12.5-32.8-12.5-45.3 0s-12.5 32.8 0 45.3l192.1 191.9z" fill="#fff" p-id="1485"></path></svg>
                            ${shortName}
                        </a>
                    </div>
                `;
                        }
                    }).join("\n");

                    // 用 images 父容器包裹
                mediaHtml = `<div style="display: flex">\n${innerHtml}\n</div>`;
            }
        }

        if (message.reactions) {
            let reactions = typeof message.reactions === 'string' ? JSON.parse(message.reactions) : message.reactions;
            if (reactions && reactions.Results && reactions.Results.length) {
                let list = reactions.Results.map(r => `<span>${r.Reaction.Emoticon} ${r.Count}</span>`).join('');
                reactionsHtml = `<div class="reactions">${list}</div>`;
            }
        }
        let widthStr = '';
        if (message.display_width) {
            widthStr = `style="max-width: ${message.display_width}px"`
        }
        return `<div ${widthStr} class="message ${position
            } clearfix">
                        <div class="date ${position
            }">${message.date}</div>
                        <div class="user ${position
            }">${message.user}</div>
                        ${replyHtml}
                        ${message.msg ? `<div class="msg">${messageContent}</div>` : ""}
                        ${mediaHtml}
                        ${ogHtml}
                        ${reactionsHtml}
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
                    img.addEventListener('load', resolve, { once: true });
                    img.addEventListener('error', resolve, { once: true });
                });
            });

            const videos = Array.from(document.querySelectorAll('video')).map(video => {
                // readyState >= 3 表示可以播放（已加载足够数据）
                if (video.readyState >= 3) return Promise.resolve();
                return new Promise(resolve => {
                    video.addEventListener('loadeddata', resolve, { once: true });
                    video.addEventListener('error', resolve, { once: true });
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
