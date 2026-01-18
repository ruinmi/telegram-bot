from telegram_bot.web_server import CleanupLinksRequest, _cleanup_link_provider
from bdpan import BaiduPanConfig, BaiduPanClient

providers = ['ali',  'baidu', 'quark', 'xunlei']
links = ['https://www.aliyundrive.com/s/N8aXBido1v1']

# def test_person(sample_data):
#     payload = CleanupLinksRequest(
#         chat_id='123', providers=['ali',  'baidu', 'quark', 'xunlei']
#     )
#     assert sample_data["name"] == "Alice"
#     assert sample_data["age"] == 25

def test_cleanup_link_provider_works():
    bdpan = BaiduPanClient(config=BaiduPanConfig(cookie_file="auth/cookies.txt"))
    assert 'ali' == _cleanup_link_provider(links[0], set(providers), bdpan=bdpan)
    