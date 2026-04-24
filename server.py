import schedule
from time import sleep, time
import traceback
import os
from tqdm import tqdm
from config.config import TARGET_TABLES, DATA_DIR, LOG_DIR
from utils.logger import LogManager
from database.mariadb import DatabaseHandler
from ftp.ftp import FTPHandler
from utils.file import FileManager
from utils.processor import DataProcessor
from datetime import datetime

# 全局处理器实例
logger = None
db_handler = None
ftp_handler = None
file_manager = None
data_processor = None
target_tables = None


def init_resources():
    """初始化资源（目录、日志、数据库连接等）"""
    global logger, db_handler, ftp_handler, file_manager, data_processor, target_tables

    # 创建必要目录
    for dir_path in [LOG_DIR, DATA_DIR]:
        os.makedirs(dir_path, exist_ok=True)

    # 初始化日志
    logger = LogManager()

    # 初始化处理器
    db_handler = DatabaseHandler(logger)
    ftp_handler = FTPHandler(logger)
    file_manager = FileManager(logger)
    data_processor = DataProcessor(db_handler, logger)
    target_tables = TARGET_TABLES

    # 打印配置信息
    logger.info("="*60)
    logger.info("🎯 跨月分表同步配置：")
    for table_info in target_tables:
        logger.info(
            f"  - {table_info['table_name']}（{table_info['year']}年{table_info['month']}月）")
    logger.info("="*60)


def run_once():
    """执行一次完整同步流程"""
    global logger, db_handler, ftp_handler, file_manager, data_processor, target_tables

    logger.info("\n" + "="*50 + " 开始执行数据同步流程 " + "="*50)
    start_time = time()
    try:
        # 1. 获取文件列表
        processed_files = db_handler.get_processed_files()
        ftp_files = ftp_handler.list_ftp_files()
        local_files = file_manager.get_local_files()

        # 2. 下载缺失文件
        downloaded_results = ftp_handler.download_missing_files(
            ftp_files, processed_files, local_files)
        download_time_map = {filename: dt for filename, dt in downloaded_results}

        # 3. 获取待处理文件
        files_to_process = file_manager.get_files_to_process(processed_files)
        if not files_to_process:
            logger.info("无待处理文件，流程结束")
            return

        # 4. 处理每个文件
        for filename in tqdm(files_to_process, desc="文件处理总进度"):
            logger.info(f"\n" + "="*40 + f" 处理文件：{filename} " + "="*40)
            total_lines, inserted, updated = data_processor.process_file(
                filename, target_tables)
            if filename in download_time_map:
                download_time = download_time_map[filename]
            else:
                file_path = os.path.join(DATA_DIR, filename)
                ctime = os.path.getctime(file_path)
                download_time = datetime.fromtimestamp(ctime)
            import_time = datetime.now()
            if db_handler.update_processed_status(
                filename,
                download_time,
                import_time,
                total_lines,
                inserted + updated
            ):
                logger.info(f"✅ 文件{filename}状态已记录到ftp_update表")
            else:
                logger.error(f"❌ 文件{filename}状态记录失败")
            
            ###
            modules_minors(db_handler)
            modules_tainei(db_handler)
            ###

        # 5. 流程汇总
        total_time = time() - start_time
        logger.info("\n" + "="*50 + " 数据同步流程完成 " + "="*50)
        logger.info(f"⏱️  总耗时：{total_time:.2f}秒")
        logger.info(f"📁 处理文件总数：{len(files_to_process)}个")
        logger.info(f"🗄️  目标表：{[t['table_name'] for t in target_tables]}")
        logger.info(
            f"📊 累计处理文件数：{len(processed_files) + len(files_to_process)}个")
    except Exception as e:
        logger.error(f"❌ 同步流程异常终止：{str(e)}")
        traceback.print_exc()
    finally:
        logger.info("="*100 + "\n")


def main():
    """主函数：初始化资源并启动定时任务"""
    # 初始化资源
    init_resources()

    # 测试数据库连接
    if not db_handler.test_connection():
        logger.error("数据库连接失败，程序退出")
        return

    # 立即执行一次
    run_once()

    # 配置定时任务（每小时5分、35分执行）
    schedule.every().hour.at(":05").do(run_once)
    schedule.every().hour.at(":35").do(run_once)
    logger.info("⏰ 定时任务已启动：每小时05分、35分自动执行")
    logger.info("💡 提示：按 Ctrl+C 可优雅停止程序")

    # 任务循环
    try:
        while True:
            schedule.run_pending()
            sleep(10)
    except KeyboardInterrupt:
        logger.info("👋 程序被用户中断，安全退出...")
    except Exception as e:
        logger.error(f"❌ 定时任务异常：{str(e)}")
        traceback.print_exc()


if __name__ == '__main__':
    main()
