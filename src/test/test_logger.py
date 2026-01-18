from telegram_bot.project_logger import get_logger

def test_logging():
    logger = get_logger()  # 获取日志实例
    logger.info("This is an info log")  # 记录一条 INFO 日志
    assert True
