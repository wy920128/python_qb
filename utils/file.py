import os
from typing import Set, List
from config.settings import DATA_DIR, FTP_CONFIG
from utils.logger import LogManager

class FileManager:
    """文件管理器（本地文件处理）"""
    def __init__(self, logger: LogManager):
        self.logger = logger

    def get_local_files(self) -> Set[str]:
        """获取本地下载目录中的文件列表"""
        if not os.path.exists(DATA_DIR):
            self.logger.warning("下载目录不存在，已自动创建")
            os.makedirs(DATA_DIR, exist_ok=True)
            return set()

        local_files = set()
        for filename in os.listdir(DATA_DIR):
            file_path = os.path.join(DATA_DIR, filename)
            if os.path.isfile(file_path) and filename.lower().endswith(FTP_CONFIG["file_suffix"]):
                local_files.add(filename)
        self.logger.info(f"本地下载目录找到{len(local_files)}个文件")
        return local_files

    def get_files_to_process(self, processed_files: Set[str]) -> List[str]:
        """获取待处理文件：本地存在、库中无"""
        local_files = self.get_local_files()
        files_to_process = [f for f in local_files if f not in processed_files]
        files_to_process.sort()  # 按文件名排序
        self.logger.info(f"待处理文件：{len(files_to_process)}个 → {files_to_process}")
        return files_to_process