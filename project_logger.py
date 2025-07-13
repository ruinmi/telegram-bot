import os
import logging

script_dir = os.path.dirname(os.path.abspath(__file__))
log_dir = os.path.join(script_dir, 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'project.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
    ]
)

class RemarkAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        remark = self.extra.get('remark')
        prefix = f'[{remark}] ' if remark else ''
        return str(prefix) + str(msg), kwargs

def get_logger(remark=None):
    base_logger = logging.getLogger('telegram_bot')
    return RemarkAdapter(base_logger, {'remark': remark})
