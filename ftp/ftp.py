from datetime import datetime
from ftplib import FTP
from typing import List, Set, Tuple
from time import sleep
from tqdm import tqdm
import os
from config.settings import FTP_CONFIG, DATA_DIR, MAX_FILE_SIZE
from utils.logger import LogManager

class FTPHandler:
    """FTP处理器（文件下载逻辑）"""
    def __init__(self, logger: LogManager):
        self.config = FTP_CONFIG
        self.logger = logger
        self.ftp = None

    def _connect_ftp(self) -> bool:
        """连接FTP（带重试）"""
        retry_count = 3
        for i in range(retry_count):
            try:
                self.ftp = FTP(self.config["host"], timeout=self.config["timeout"])
                self.ftp.login(self.config["user"], self.config["passwd"])
                self.ftp.cwd(self.config.get("remote_path", ""))
                self.logger.info("✅ FTP连接成功")
                return True
            except Exception as e:
                self.logger.warning(f"第{i+1}次FTP连接失败：{str(e)}")
                sleep(2)
        self.logger.error("❌ FTP连接失败（已重试3次）")
        return False

    def list_ftp_files(self) -> List[str]:
        """获取FTP上的目标文件列表"""
        if not self._connect_ftp():
            return []

        try:
            file_list = []
            self.ftp.retrlines("NLST", file_list.append)
            target_files = [f for f in file_list if f.lower().endswith(self.config["file_suffix"])]
            self.logger.info(f"FTP服务器找到{len(target_files)}个目标文件")
            return target_files
        except Exception as e:
            self.logger.error(f"获取FTP文件列表失败：{str(e)}")
            return []
        finally:
            if self.ftp:
                self.ftp.quit()

    def download_missing_files(self, ftp_files: List[str], processed_files: Set[str], local_files: Set[str]) -> List[Tuple[str, datetime]]:
        """下载文件并返回 (文件名, 下载时间) 列表"""
        files_to_download = [
            f for f in ftp_files
            if f not in processed_files and f not in local_files
        ]
        if not files_to_download:
            self.logger.info("无需要下载的文件（所有FTP文件已在本地或已处理）")
            return []
        self.logger.info(f"需要下载{len(files_to_download)}个文件：{files_to_download}")
        if not self._connect_ftp():
            return []
        downloaded_results = []
        for filename in tqdm(files_to_download, desc="FTP文件下载"):
            local_path = os.path.join(DATA_DIR, filename)
            try:
                file_size = self.ftp.size(filename)
                if file_size > MAX_FILE_SIZE:
                    self.logger.warning(f"文件{filename}超过200MB限制（{file_size/1024/1024:.1f}MB），跳过")
                    continue
                with open(local_path, 'wb') as f:
                    self.ftp.retrbinary(f"RETR {filename}", f.write, blocksize=8192)
                download_time = datetime.now()
                downloaded_results.append((filename, download_time))
                self.logger.info(f"文件{filename}下载成功（大小：{file_size/1024/1024:.1f}MB，时间：{download_time}）")
            except Exception as e:
                self.logger.error(f"文件{filename}下载失败：{str(e)}")
                # 清理残留文件
                if os.path.exists(local_path):
                    os.remove(local_path)
                continue
        self.ftp.quit()
        self.logger.info(f"下载完成：成功{len(downloaded_results)}个，失败{len(files_to_download)-len(downloaded_results)}个")
        return downloaded_results