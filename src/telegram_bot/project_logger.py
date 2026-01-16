import os
import logging

from .paths import LOGS_DIR, ensure_runtime_dirs

ensure_runtime_dirs()
log_file = str(LOGS_DIR / 'project.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
    ]
)

class RemarkAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        remark = self.extra.get('remark') if self.extra else None
        prefix = f'[{remark}] ' if remark else ''
        return str(prefix) + str(msg), kwargs

def get_logger(remark=None):
    base_logger = logging.getLogger('telegram_bot')
    return RemarkAdapter(base_logger, {'remark': remark})
