from telegram_bot import message_utils

class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def json(self):
        return self._payload


def test_is_ali_link_stale(monkeypatch):
    def fake_post(url, headers=None, json=None, params=None):
        share_id = url.split("share_id=", 1)[1]
        if share_id == "missing_share_name":
            return _FakeResponse({"code": 200})
        if share_id == "empty_files_no_pwd":
            return _FakeResponse({"share_name": "x", "has_pwd": False, "file_infos": []})
        if share_id == "ok":
            return _FakeResponse({"share_name": "x", "has_pwd": False, "file_infos": [{"name": "a"}]})
        raise AssertionError("unexpected share_id")

    monkeypatch.setattr(message_utils, "http_post", fake_post)

    assert message_utils.is_ali_link_stale("https://www.alipan.com/s/missing_share_name") is True
    assert message_utils.is_ali_link_stale("https://www.alipan.com/s/empty_files_no_pwd") is True
    assert message_utils.is_ali_link_stale("https://www.alipan.com/s/ok") is False
        
