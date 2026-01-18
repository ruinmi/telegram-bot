// 创建可点击的分隔符元素，通过接口按需加载上下文消息（按 msg_id 取区间）
export function createSeparatorElement(gapId, startMsgId, endMsgId, direction, searchValue) {
    let separator = document.createElement('div');
    separator.className = 'separator ' + direction;
    separator.dataset.gapId = String(gapId);
    separator.dataset.startMsgId = String(startMsgId);
    separator.dataset.endMsgId = String(endMsgId);
    separator.dataset.direction = direction;
    if (direction === "up") {
        separator.innerHTML = ' <span style="color: #aaa; font-size: 0.9rem;"><svg t="1768730340153" class="icon" viewBox="0 0 1394 1024" version="1.1" xmlns="http://www.w3.org/2000/svg" p-id="1683" width="16" height="16"><path d="M808.676766 55.862468l557.622468 743.685447c46.363234 61.83217 34.03166 149.700085-27.539064 196.259404A139.176851 139.176851 0 0 1 1254.813957 1024H139.569021C62.485787 1024 0 961.252766 0 883.842723a140.52766 140.52766 0 0 1 28.061957-84.316595L585.684426 55.884255a139.176851 139.176851 0 0 1 222.99234 0z" fill="#e6e6e6" p-id="1684"></path></svg></span>';
    } else {
        separator.innerHTML = '<span style="color: #aaa; font-size: 0.9rem;"><svg t="1768729129514" class="icon" viewBox="0 0 1394 1024" version="1.1" xmlns="http://www.w3.org/2000/svg" p-id="1683" width="16" height="16"><path d="M808.665066 968.123525a139.174837 139.174837 0 0 1-222.989114 0L28.061551 224.448838A140.525626 140.525626 0 0 1 0 140.133462C0 62.746326 62.484883 0 139.567002 0h1115.228801c30.283817 0 59.739731 9.891261 83.944998 28.192273 61.569833 46.558646 73.901229 134.425289 27.538666 196.256565L808.665066 968.123525z" fill="#e6e6e6" p-id="1684"></path></svg></span>';
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