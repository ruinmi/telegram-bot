from telegram_bot.web_server import _cleanup_link_provider


class _FakeBdPan:
    def is_share_link(self, link: str) -> bool:
        return "pan.baidu.com" in link


providers = ['ali', 'baidu', 'quark', 'xunlei']
links = ['https://www.aliyundrive.com/s/N8aXBido1v1']


def test_cleanup_link_provider_works():
    bdpan = _FakeBdPan()
    assert 'ali' == _cleanup_link_provider(links[0], set(providers), bdpan=bdpan)
