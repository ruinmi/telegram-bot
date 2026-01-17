from time import time
import uuid
from telegram_bot.http_client import get as http_get
from telegram_bot.http_client import post as http_post
import hashlib
import execjs

def __words_to_bytes(e):
    t = []
    for b in range(0, 32 * len(e), 8):
        index = b >> 5  # b >>> 5 in JS is b >> 5 in Python
        # 模拟无符号右移
        byte = ((e[index] & 0xFFFFFFFF) >> (24 - b % 32)) & 255
        t.append(byte)
    return t

def __bytesToHex(e):
    t = []
    for byte in e:
        t.append(format((byte >> 4) & 0x0F, 'x'))
        t.append(format(byte & 0x0F, 'x'))
    return ''.join(t)

def __cipher1(e):
    # 如果是字符串，转换为字节数组
    if isinstance(e, str):
        e = e.encode('utf-8')
    
    # 创建 MD5 哈希对象
    md5_hash = hashlib.md5()

    # 更新哈希对象
    md5_hash.update(e)

    # 获取 MD5 哈希值的十六进制表示
    digest = md5_hash.digest()  # 返回一个字节串

    # 将字节串拆分为四个 32 位整数（每个整数包含 4 个字节）
    result = []
    for i in range(0, 16, 4):
        # 每四个字节组合成一个 32 位整数
        val = int.from_bytes(digest[i:i+4], byteorder='big', signed=True)
        result.append(val)

    return result

def __get_captcha_sign(input):
    js_code = """
    function m(input) {
        var i, output = [];
        for (output[(input.length >> 2) - 1] = void 0,
        i = 0; i < output.length; i += 1)
            output[i] = 0;
        var e = 8 * input.length;
        for (i = 0; i < e; i += 8)
            output[i >> 5] |= (255 & input.charCodeAt(i / 8)) << i % 32;
        return output
    }
    function o(e, t) {
        var r = (65535 & e) + (65535 & t);
        return (e >> 16) + (t >> 16) + (r >> 16) << 16 | 65535 & r
    }
    function c(q, a, b, e, s, t) {
        return o((r = o(o(a, q), o(e, t))) << (n = s) | r >>> 32 - n, b);
        var r, n
    }
    function l(a, b, e, t, r, s, n) {
        return c(b & e | ~b & t, a, b, r, s, n)
    }
    function d(a, b, e, t, r, s, n) {
        return c(b & t | e & ~t, a, b, r, s, n)
    }
    function f(a, b, e, t, r, s, n) {
        return c(b ^ e ^ t, a, b, r, s, n)
    }
    function h(a, b, e, t, r, s, n) {
        return c(e ^ (b | ~t), a, b, r, s, n)
    }
    function _(e, t) {
        var i, r, n, c, _;
        e[t >> 5] |= 128 << t % 32,
        e[14 + (t + 64 >>> 9 << 4)] = t;
        var a = 1732584193
            , b = -271733879
            , v = -1732584194
            , m = 271733878;
        for (i = 0; i < e.length; i += 16)
            r = a,
            n = b,
            c = v,
            _ = m,
            a = l(a, b, v, m, e[i], 7, -680876936),
            m = l(m, a, b, v, e[i + 1], 12, -389564586),
            v = l(v, m, a, b, e[i + 2], 17, 606105819),
            b = l(b, v, m, a, e[i + 3], 22, -1044525330),
            a = l(a, b, v, m, e[i + 4], 7, -176418897),
            m = l(m, a, b, v, e[i + 5], 12, 1200080426),
            v = l(v, m, a, b, e[i + 6], 17, -1473231341),
            b = l(b, v, m, a, e[i + 7], 22, -45705983),
            a = l(a, b, v, m, e[i + 8], 7, 1770035416),
            m = l(m, a, b, v, e[i + 9], 12, -1958414417),
            v = l(v, m, a, b, e[i + 10], 17, -42063),
            b = l(b, v, m, a, e[i + 11], 22, -1990404162),
            a = l(a, b, v, m, e[i + 12], 7, 1804603682),
            m = l(m, a, b, v, e[i + 13], 12, -40341101),
            v = l(v, m, a, b, e[i + 14], 17, -1502002290),
            a = d(a, b = l(b, v, m, a, e[i + 15], 22, 1236535329), v, m, e[i + 1], 5, -165796510),
            m = d(m, a, b, v, e[i + 6], 9, -1069501632),
            v = d(v, m, a, b, e[i + 11], 14, 643717713),
            b = d(b, v, m, a, e[i], 20, -373897302),
            a = d(a, b, v, m, e[i + 5], 5, -701558691),
            m = d(m, a, b, v, e[i + 10], 9, 38016083),
            v = d(v, m, a, b, e[i + 15], 14, -660478335),
            b = d(b, v, m, a, e[i + 4], 20, -405537848),
            a = d(a, b, v, m, e[i + 9], 5, 568446438),
            m = d(m, a, b, v, e[i + 14], 9, -1019803690),
            v = d(v, m, a, b, e[i + 3], 14, -187363961),
            b = d(b, v, m, a, e[i + 8], 20, 1163531501),
            a = d(a, b, v, m, e[i + 13], 5, -1444681467),
            m = d(m, a, b, v, e[i + 2], 9, -51403784),
            v = d(v, m, a, b, e[i + 7], 14, 1735328473),
            a = f(a, b = d(b, v, m, a, e[i + 12], 20, -1926607734), v, m, e[i + 5], 4, -378558),
            m = f(m, a, b, v, e[i + 8], 11, -2022574463),
            v = f(v, m, a, b, e[i + 11], 16, 1839030562),
            b = f(b, v, m, a, e[i + 14], 23, -35309556),
            a = f(a, b, v, m, e[i + 1], 4, -1530992060),
            m = f(m, a, b, v, e[i + 4], 11, 1272893353),
            v = f(v, m, a, b, e[i + 7], 16, -155497632),
            b = f(b, v, m, a, e[i + 10], 23, -1094730640),
            a = f(a, b, v, m, e[i + 13], 4, 681279174),
            m = f(m, a, b, v, e[i], 11, -358537222),
            v = f(v, m, a, b, e[i + 3], 16, -722521979),
            b = f(b, v, m, a, e[i + 6], 23, 76029189),
            a = f(a, b, v, m, e[i + 9], 4, -640364487),
            m = f(m, a, b, v, e[i + 12], 11, -421815835),
            v = f(v, m, a, b, e[i + 15], 16, 530742520),
            a = h(a, b = f(b, v, m, a, e[i + 2], 23, -995338651), v, m, e[i], 6, -198630844),
            m = h(m, a, b, v, e[i + 7], 10, 1126891415),
            v = h(v, m, a, b, e[i + 14], 15, -1416354905),
            b = h(b, v, m, a, e[i + 5], 21, -57434055),
            a = h(a, b, v, m, e[i + 12], 6, 1700485571),
            m = h(m, a, b, v, e[i + 3], 10, -1894986606),
            v = h(v, m, a, b, e[i + 10], 15, -1051523),
            b = h(b, v, m, a, e[i + 1], 21, -2054922799),
            a = h(a, b, v, m, e[i + 8], 6, 1873313359),
            m = h(m, a, b, v, e[i + 15], 10, -30611744),
            v = h(v, m, a, b, e[i + 6], 15, -1560198380),
            b = h(b, v, m, a, e[i + 13], 21, 1309151649),
            a = h(a, b, v, m, e[i + 4], 6, -145523070),
            m = h(m, a, b, v, e[i + 11], 10, -1120210379),
            v = h(v, m, a, b, e[i + 2], 15, 718787259),
            b = h(b, v, m, a, e[i + 9], 21, -343485551),
            a = o(a, r),
            b = o(b, n),
            v = o(v, c),
            m = o(m, _);
        return [a, b, v, m]
    }
    function v(input) {
        var i, output = "", e = 32 * input.length;
        for (i = 0; i < e; i += 8)
            output += String.fromCharCode(input[i >> 5] >>> i % 32 & 255);
        return output
    }
    function y(input) {
        var e, i, t = "0123456789abcdef", output = "";
        for (i = 0; i < input.length; i += 1)
            e = input.charCodeAt(i),
            output += t.charAt(e >>> 4 & 15) + t.charAt(15 & e);
        return output
    }
    function x(e, t) {
        return function(e, data) {
            var i, t, r = m(e), n = [], o = [];
            for (n[15] = o[15] = void 0,
            r.length > 16 && (r = _(r, 8 * e.length)),
            i = 0; i < 16; i += 1)
                n[i] = 909522486 ^ r[i],
                o[i] = 1549556828 ^ r[i];
            return t = _(n.concat(m(data)), 512 + 8 * data.length),
            v(_(o.concat(t), 640))
        }(E(e), E(t))
    }
    function E(input) {
        return unescape(encodeURIComponent(input))
    }
    function I(s) {
        return function(s) {
            return v(_(m(s), 8 * s.length))
        }(E(s))
    }
    function T(e, t, r) {
        return t ? r ? x(t, e) : y(x(t, e)) : r ? I(e) : y(I(e))
    }
    """
    ctx = execjs.compile(js_code)
    result = ctx.call("T", input + "hL2EnGDpOVDQ301IhFcpwOMD7")
    result = ctx.call("T", result + 'oFu3pD/M95loyNGxhRt7x8U3E/WKVBHE5kvcecEhp889')
    result = ctx.call("T", result + 'px3MA6YEqr')
    result = ctx.call("T", result + "VwtLx9JBmTZtdt0Ph6K/uGScbUYbjOXwZTb8+dAhwWXT")
    result = ctx.call("T", result + "hs95CVCKD0Jpmr2u")
    result = ctx.call("T", result + "S7iJxVIWWsuVLx6HOP6MdJjlIix8yUPkr0VL")
    result = ctx.call("T", result + "RubOWgrG3Myw9Isw")
    result = ctx.call("T", result + "SxbRZnxFWlZBxbjakkYkO4FLGQQLygDwThI86erSOefn32gppN")
    result = "1." + ctx.call("T", result + "pX+3O1MP4Ah")
    return result

def __sign_xl_fp(fp_raw):
    resp = http_get(
        f'https://xluser-ssl.xunlei.com/risk?cmd=algorithm&t={int(time() * 1000)}'
    )
    javascript_code = resp.text + f"\nxl_al('{fp_raw}')"
    ctx = execjs.compile(javascript_code)
    return ctx.call("xl_al", fp_raw)
    
def _generate_xunlei_device_id():
    xl_fp_raw = uuid.uuid4().hex
    xl_fp = __bytesToHex(__words_to_bytes(__cipher1(xl_fp_raw)))
    xl_fp_sign = __sign_xl_fp(xl_fp_raw)
    body = {
        "xl_fp_raw": xl_fp_raw,
        "xl_fp": xl_fp,
        "version": 2,
        "xl_fp_sign": xl_fp_sign
    }
    url = 'https://xluser-ssl.xunlei.com/risk?cmd=report'
    resp = http_post(url, json=body)
    device_sign = resp.json().get('deviceid')
    device_id = device_sign.split('.')[1][:32]
    return device_id

def _generate_captcha_token(device_id):
    url = 'https://xluser-ssl.xunlei.com/v1/shield/captcha/init'
    ts = int(time() * 1000)
    request_payload = {
        'action': "get:/drive/v1/share",
        'client_id': "Xqp0kJBXWhwaTpB6", # 应该固定的,
        'device_id': device_id,
        'meta': {
            'captcha_sign': __get_captcha_sign(f'Xqp0kJBXWhwaTpB6' + '1.92.33' + 'pan.xunlei.com' + device_id + str(ts)),
            'client_version': '1.92.33',
            'email': '',
            'package_name': 'pan.xunlei.com',
            'phone_number': '',
            'timestamp': f'{ts}',
            'user_id': '0',
            'username': '',
        }
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Referer': 'https://pan.xunlei.com/',
        'Content-Type': 'text/plain; charset=utf-8'
    }
    resp = http_post(url, json=request_payload, headers=headers)
    captcha_token = resp.json().get('captcha_token')
    return captcha_token

def is_xunlei_link_stale(link: str) -> bool:
    """Check if a Xunlei link is stale."""
    
    url = 'https://api-pan.xunlei.com/drive/v1/share'
    params = {
        'share_id': link.split('/s/')[1].split('?')[0],
        'pass_code': '',
        'limit': 100,
        'pass_code_token': '',
        'page_token': '',
        'thumbnail_size': 'SIZE_SMALL',
    }
    device_id = _generate_xunlei_device_id()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Referer': 'https://pan.xunlei.com/',
        'Content-Type': 'application/json',
        'x-captcha-token': _generate_captcha_token(device_id),
        'x-client-id': 'Xqp0kJBXWhwaTpB6',
        'x-device-id': device_id,
    }
    resp = http_get(url, params=params, headers=headers)
    data = resp.json()
    if data.get('share_status') != 'PASS_CODE_EMPTY':
        return True
    return False

