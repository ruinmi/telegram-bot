from fastapi.testclient import TestClient

from telegram_bot.web_server import _cleanup_link_provider, app


class _FakeBdPan:
    def is_share_link(self, link: str) -> bool:
        return "pan.baidu.com" in link


providers = ['ali', 'baidu', 'quark', 'xunlei']
links = ['https://www.aliyundrive.com/s/N8aXBido1v1']


def test_cleanup_link_provider_works():
    bdpan = _FakeBdPan()
    assert 'ali' == _cleanup_link_provider(links[0], set(providers), bdpan=bdpan)


def test_index_page_renders_successfully():
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/")

    assert response.status_code == 200
    assert "聊天频道管理" in response.text
