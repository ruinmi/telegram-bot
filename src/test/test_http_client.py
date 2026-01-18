from telegram_bot.http_client import post as http_post
from tenacity import Future, RetryCallState, Retrying, retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter, wait_incrementing

def test_http_post_retry_429():
    url = 'https://httpbin.org/status/429'
    resp = http_post(url)
    assert resp.status_code == 429
    
