from telegram_bot.message_utils import is_ali_link_stale

def stest_is_ali_link_stale():
    links = ['https://www.aliyundrive.com/s/N8aXBido1v1', 'https://www.aliyundrive.com/s/DDyhz7BGAf5', 'https://www.aliyundrive.com/s/HDKJxswXQxX', 'https://www.aliyundrive.com/s/4Mx8bHHgSVw']
    expected_results = [True, True, False, True]
    for i, link in enumerate(links):
        assert is_ali_link_stale(link) == expected_results[i]
        