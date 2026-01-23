from telegram_bot.message_utils import is_ali_link_stale

def test_is_ali_link_stale():
    links = ['https://www.alipan.com/s/C5MTVVHofUE', 'https://www.alipan.com/s/Rr5bTFNv385', 'https://www.alipan.com/s/UhvvsMFFsMy']
    expected_results = [True, False, False]
    for i, link in enumerate(links):
        assert is_ali_link_stale(link) == expected_results[i]
        