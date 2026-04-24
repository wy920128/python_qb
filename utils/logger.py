import os
import logging
from datetime import datetime
from config.config import LOG_DIR

class LogManager:
    """日志管理器（输出到 ./logs/ 目录）"""
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False  # 避免重复输出

        if not self.logger.handlers:
            # 日志格式
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)-6s | %(filename)s:%(lineno)d | %(message)s'
            )

            # 控制台处理器
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

            # 文件处理器
            os.makedirs(LOG_DIR, exist_ok=True)
            log_file = os.path.join(LOG_DIR, f"ftp_data_process_{datetime.now().strftime('%Y%m%d')}.log")
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    def info(self, msg: str):
        self.logger.info(msg)

    def error(self, msg: str):
        self.logger.error(msg)

    def warning(self, msg: str):
        self.logger.warning(msg)

    def debug(self, msg: str):
        self.logger.debug(msg)