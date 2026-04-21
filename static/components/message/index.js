import { resolveMediaUrl, applyImageFallback, isPhone } from '../../utils.js';

const DEFAULT_MAX_IMG_HEIGHT = window.innerHeight * 0.5;
const chatUsername = window.CHAT_USERNAME || '';

/**
 * 计算单张图片最大宽度(px)，基于「气泡」的内容区宽度
 */
function calculateMaxImageWidth(containerEl, imagesPerRow = 3, gap = 6) {
    // 找到最近的气泡容器
    const bubbleEl = containerEl.closest('.message-frame');
    const bubbleStyle = window.getComputedStyle(bubbleEl);

    // 气泡内容区真实可用宽度 = clientWidth – 内边距
    const bubbleInnerWidth = bubbleEl.clientWidth
        - parseFloat(bubbleStyle.paddingLeft)
        - parseFloat(bubbleStyle.paddingRight);
    
    const widthForCal = Math.max(bubbleInnerWidth, isPhone() ? 320 : 600);

    // 每张图可用宽度 = (可用宽 – 间距总和) / 张数
    return Math.floor(
        (widthForCal - gap * (imagesPerRow - 1))
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
        ? 1 :
        imageList.length === 2
            ? 2
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
        if (options.telegramUrl) {
            tile.dataset.telegramUrl = options.telegramUrl;
        }
        tile.style.zIndex = '1';
        tile.style.width = `${w}px`;
        tile.style.height = `${h}px`;
        tile.appendChild(image);
        containerEl.appendChild(tile);
    });
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

function _linkifyHtml(html) {
  const container = document.createElement("div");
  container.innerHTML = html;

  const urlRegex = /https?:\/\/[^\s<>"')\]]+/g;

  const walker = document.createTreeWalker(
    container,
    NodeFilter.SHOW_TEXT,
    null
  );

  const textNodes = [];
  let node;
  while ((node = walker.nextNode())) {
    // 跳过 a 标签内部，避免重复 link
    if (node.parentNode?.closest("a")) continue;
    textNodes.push(node);
  }

  for (const textNode of textNodes) {
    const text = textNode.nodeValue;
    if (!urlRegex.test(text)) continue;

    const frag = document.createDocumentFragment();
    let lastIndex = 0;

    text.replace(urlRegex, (url, index) => {
      // 前面的普通文本
      frag.append(text.slice(lastIndex, index));

      // a 标签
      const a = document.createElement("a");
      a.href = url;
      a.textContent = url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      frag.append(a);

      lastIndex = index + url.length;
    });

    frag.append(text.slice(lastIndex));
    textNode.replaceWith(frag);
  }

  return container.innerHTML;
}



// 根据单个消息数据生成 HTML 结构
export function createMessageHtml(message, index, searchValue) {
    const position = Number(message.is_self) === 1 || message.user === '我' ? 'right' : 'left';
    const telegramUrl = chatUsername ? `https://t.me/${chatUsername}/${message.msg_id ?? ''}` : `https://t.me/c/${message.chat_id}/${message.msg_id ?? ''}`;

    // 1. 文本内容
    let messageContent = message.msg
        ? highlightText(message.msg, searchValue)
        : '';
    messageContent = _linkifyHtml(messageContent).replace(/\n/g, '<br/>');

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
            const replyTelegramUrl = chatUsername ? `https://t.me/${chatUsername}/${d.msg_id ?? ''}` : `https://t.me/c/${message.chat_id}/${d.msg_id ?? ''}`;
            imgPart = `<div class="reply-image">
                   <div class="img-tile reply-image__btn" data-img-src="${src}" data-telegram-url="${replyTelegramUrl}">
                     <img src="${src}" alt="图片" loading="lazy">
                   </div>
                 </div>`;
        } else if (d.msg_files) {
            const files = Array.isArray(d.msg_files)
                ? d.msg_files
                : JSON.parse(d.msg_files);
            const replyTelegramUrl = chatUsername ? `https://t.me/${chatUsername}/${d.msg_id ?? ''}` : `https://t.me/c/${message.chat_id}/${d.msg_id ?? ''}`;
            imgPart = files.map(fn =>
                /\.(png|jpe?g|gif|webp)$/i.test(fn)
                    ? `<div class="reply-image"><div class="img-tile reply-image__btn" data-img-src="${resolveMediaUrl(fn)}" data-telegram-url="${replyTelegramUrl}"><img src="${resolveMediaUrl(fn)}" alt="图片" loading="lazy"></div></div>`
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
                telegramUrl,
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

    const repliesNum = Number(message.replies_num ?? 0) || 0;
    const repliesBadgeHtml = repliesNum > 0 && message.msg_id != null
        ? `<span class="replies-badge" role="button" tabindex="0" data-reply-to-msg-id="${message.msg_id}" title="查看回复">
        ${repliesNum}
        <svg t="1769777258787" class="icon" viewBox="0 0 1024 1024" version="1.1" xmlns="http://www.w3.org/2000/svg" p-id="2530" width="12" height="12"><path d="M356.650667 155.008q17.322667 0 29.994667 12.501333t12.672 30.165333-12.672 30.336l-198.656 198.656 409.344 0q77.994667 0 149.162667 30.336t122.496 81.834667 81.834667 122.496 30.506667 149.333333l0 42.666667q0 17.664-12.501333 30.165333t-30.165333 12.501333q-17.322667 0-29.994667-12.672t-12.672-29.994667l0-42.666667q0-60.672-23.68-116.010667t-63.658667-95.317333-95.317333-63.658667-116.010667-23.68l-409.344 0 198.656 198.997333q12.672 12.672 12.672 29.994667 0 17.664-12.501333 30.336t-30.165333 12.672-30.336-12.672l-271.317333-271.658667q-12.330667-12.330667-12.330667-30.336 0-17.664 12.330667-29.994667l271.317333-271.658667q12.672-12.672 30.336-12.672z" p-id="2531" fill="#dbdbdb"></path></svg>        </span>`
        : '';

    // 6. 拼接整体
    return `
    <div class="message ${hasImage} ${position} clearfix" data-msg-id="${message.msg_id ?? ''}">
      <div class="message-row ${position}">
        <div class="message-frame ${position}">
          <div class="user ${position}">${message.user}</div>
          ${replyHtml}
          ${mediaHtml}
          ${message.msg ? `<div class="msg">${messageContent}</div>` : ''}
          ${ogHtml}
          ${reactionsHtml}
          <div class="date ${position}">${repliesBadgeHtml}<span class="date-text">${message.date}</span></div>
        </div>
        <div class="message-to-telegram ${position}" data-telegram-url="${telegramUrl}">
          <a href="${telegramUrl}" target="_blank" rel="noopener noreferrer"></a>
          <span class="to-icon"></span>
        </div>
      </div>
    </div>`;
}
