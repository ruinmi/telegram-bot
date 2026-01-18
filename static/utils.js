
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

export function htmlToElement(html) {
    const tpl = document.createElement('template');
    tpl.innerHTML = (html || '').trim();
    return tpl.content.firstElementChild;
}

export function resolveMediaUrl(url) {
    const raw = (url || '').trim();
    if (!raw) return '';
    if (/^https?:\/\//i.test(raw)) return raw;

    let cleaned = raw;
    while (cleaned.startsWith('../')) cleaned = cleaned.slice(3);
    if (cleaned.startsWith('./')) cleaned = cleaned.slice(2);

    if (cleaned.startsWith('/')) return cleaned;
    return `/${cleaned}`;
}

export function applyImageFallback(imgEl) {
    if (!imgEl) return;
    if (imgEl.dataset.fallbackApplied === '1') return;
    imgEl.dataset.fallbackApplied = '1';
    imgEl.classList.add('img-broken');
    imgEl.src = BROKEN_IMAGE_PLACEHOLDER;
}

export function isPhone() {
  const userAgent = navigator.userAgent.toLowerCase();

  // 判断是否为手机端
  if (/mobile/i.test(userAgent)) {
    return true;
  }
  return false;
}

