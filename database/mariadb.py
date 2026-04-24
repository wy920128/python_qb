from datetime import datetime
import mariadb
from config.config import (
    DB_CONFIG, TARGET_TABLES, BUSINESS_FIELDS, UNIQUE_KEY_FIELDS
)
from dbutils.pooled_db import PooledDB
from time import sleep
from typing import List, Set, Tuple, Optional, Any, Union
from utils.logger import LogManager

MariaDBError = mariadb.Error
MariaDBOperationalError = mariadb.OperationalError


class DatabaseHandler:
    """数据库处理器（适配跨月双表，基于MariaDB驱动）"""

    def __init__(self, logger: LogManager):
        self.config = self._adapt_mariadb_config(DB_CONFIG)
        self.logger = logger
        self.pool = self._init_connection_pool()
        self._ensure_processed_table()
        self._ensure_temp_table()
        for table_info in TARGET_TABLES:
            self.ensure_target_table(table_info["table_name"])

    def _adapt_mariadb_config(self, raw_config: dict) -> dict:
        """适配MariaDB连接配置"""
        mariadb_config = raw_config.copy()
        if 'charset' in mariadb_config:
            mariadb_config['charset'] = mariadb_config.pop('charset')
        mariadb_config['port'] = int(mariadb_config.get('port', 3306))
        mariadb_config.setdefault('connect_timeout', 10)
        return mariadb_config

    def _init_connection_pool(self) -> PooledDB:
        """初始化MariaDB连接池"""
        try:
            pool_config = {k: v for k, v in self.config.items() if k not in [
                'local_infile']}
            return PooledDB(
                creator=mariadb,
                maxconnections=15,
                mincached=3,
                maxcached=8,
                blocking=True,
                maxusage=None,
                **pool_config
            )
        except MariaDBError as e:
            self.logger.error(f"MariaDB连接池初始化失败：{str(e)}")
            raise

    def get_connection(self) -> Optional[mariadb.connections.Connection]:
        """获取数据库连接（带重试机制）"""
        retry_count = 3
        for i in range(retry_count):
            try:
                conn = self.pool.connection()
                if conn:
                    conn.ping()
                    return conn
            except MariaDBOperationalError as e:
                self.logger.warning(f"第{i+1}次获取连接失败（网络/连接异常）：{str(e)}")
                sleep(1)
            except MariaDBError as e:
                self.logger.warning(f"第{i+1}次获取连接失败：{str(e)}")
                sleep(1)
        self.logger.error("获取MariaDB连接失败（已重试3次）")
        return None

    def get_processed_files(self) -> Set[str]:
        """从 ftp_更新表 获取已处理的文件名"""
        sql = "SELECT DISTINCT `文件名` FROM `ftp_更新表`"
        conn = None
        try:
            conn = self.get_connection()
            if not conn:
                return set()
            with conn.cursor() as cursor:
                cursor.execute(sql)
                results = cursor.fetchall()
                return {row[0] for row in results} if results else set()
        except MariaDBError as e:
            self.logger.error(f"获取已处理文件列表失败：{str(e)}")
            return set()
        finally:
            if conn:
                conn.close()

    def _ensure_processed_table(self) -> bool:
        """创建 ftp_更新表（文件处理状态表）"""
        sql = """
        CREATE TABLE IF NOT EXISTS `ftp_更新表` (
            `id` int(11) NOT NULL AUTO_INCREMENT COMMENT '自增主键',
            `文件名` varchar(255) NOT NULL COMMENT 'FTP文件名',
            `下载时间` datetime NOT NULL COMMENT '文件下载完成时间',
            `入库时间` datetime NOT NULL COMMENT '数据入库完成时间',
            `数据量` int(11) NOT NULL DEFAULT 0 COMMENT '原TXT文件总行数',
            `更新量` int(11) NOT NULL DEFAULT 0 COMMENT '入库的新数据行数',
            PRIMARY KEY (`id`),
            UNIQUE KEY `uk_filename` (`文件名`) COMMENT '文件名唯一，避免重复处理'
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='FTP文件处理状态表';
        """
        return self._execute_sql(sql, commit=True)

    def _ensure_temp_table(self) -> bool:
        """创建 ftp_临时表 表（17个业务字段）"""
        fields_sql = self._build_fields_sql()
        unique_key_str = ', '.join(
            [f'`{field}`' for field in UNIQUE_KEY_FIELDS])
        sql = f"""
        CREATE TABLE IF NOT EXISTS `ftp_临时表` (
            `id` int(11) NOT NULL AUTO_INCREMENT COMMENT '自增主键',
            {fields_sql},
            PRIMARY KEY (`id`),
            UNIQUE KEY `uk_temp_all_fields` ({unique_key_str}) COMMENT '全业务字段唯一，预处理去重'
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='FTP数据临时处理表';
        """
        return self._execute_sql(sql, commit=True)

    def ensure_target_table(self, table_name: str) -> bool:
        """创建目标表（适配17个字段，校验表名格式）"""
        fields_sql = self._build_fields_sql()
        unique_key_str = ', '.join(
            [f'`{field}`' for field in UNIQUE_KEY_FIELDS])
        sql = f"""
        CREATE TABLE IF NOT EXISTS `{table_name}` (
            `id` int(11) NOT NULL AUTO_INCREMENT COMMENT '自增主键ID',
            {fields_sql},
            `创建时间` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
            `更新时间` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',
            `删除时间` datetime DEFAULT NULL COMMENT '软删除标记',
            PRIMARY KEY (`id`) USING BTREE COMMENT '主键索引',
            UNIQUE KEY `uk_all_business_fields` ({unique_key_str}) USING BTREE COMMENT '全业务字段唯一索引',
            INDEX `idx_train_no` (`车次`) USING BTREE COMMENT '按车次查询',
            INDEX `idx_travel_date` (`乘车日期`) USING BTREE COMMENT '按乘车日期查询',
            INDEX `idx_id_card` (`证件类型`, `证件编号`) USING BTREE COMMENT '按证件信息查询',
            INDEX `idx_depart_arrive` (`发站`, `到站`) USING BTREE COMMENT '按发站+到站查询',
            INDEX `idx_soft_delete` (`删除时间`) USING BTREE COMMENT '软删除过滤'
        ) ENGINE=InnoDB AUTO_INCREMENT=1 CHARACTER SET=utf8mb4 COLLATE=utf8mb4_general_ci ROW_FORMAT=Dynamic COMMENT='{table_name}';
        """
        return self._execute_sql(sql, commit=True)

    def _build_fields_sql(self) -> str:
        """构建业务字段SQL（修复末尾多余逗号问题）"""
        fields_sql_parts = []
        field_comments = {
            '车次': '列车车次',
            '乘车日期': '乘车日期（yyyy-mm-dd）',
            '乘车时间': '乘车时间（hh:mm:ss）',
            '发站': '发站',
            '到站': '到站',
            '售票处': '售票处编号/名称',
            '售票时间': '售票时间',
            '票号': '车票编号',
            '票价': '车票价格',
            '车厢号': '车厢号',
            '座位号': '座位号',
            '席别': '席别',
            '窗口': '窗口',
            '票种': '票种',
            '姓名': '乘车人姓名',
            '证件类型': '证件类型',
            '证件编号': '证件编号'
        }
        for field in BUSINESS_FIELDS:
            if field not in field_comments:
                self.logger.warning(f"未知业务字段：{field}，跳过构建")
                continue
            if field == '车次':
                field_def = f'`{field}` varchar(8) NOT NULL COMMENT \'{field_comments[field]}\''
            elif field in ['乘车日期', '乘车时间', '售票时间']:
                field_type = 'date' if field == '乘车日期' else 'time' if field == '乘车时间' else 'datetime'
                field_def = f'`{field}` {field_type} NOT NULL COMMENT \'{field_comments[field]}\''
            elif field in ['发站', '到站']:
                field_def = f'`{field}` varchar(32) NOT NULL COMMENT \'{field_comments[field]}\''
            elif field == '售票处':
                field_def = f'`{field}` varchar(16) NOT NULL COMMENT \'{field_comments[field]}\''
            elif field == '票号':
                field_def = f'`{field}` varchar(32) NOT NULL COMMENT \'{field_comments[field]}\''
            elif field == '票价':
                field_def = f'`{field}` decimal(10,2) DEFAULT NULL COMMENT \'{field_comments[field]}\''
            elif field in ['车厢号', '座位号', '席别', '窗口', '票种']:
                field_def = f'`{field}` varchar(8) DEFAULT NULL COMMENT \'{field_comments[field]}\''
            elif field == '姓名':
                field_def = f'`{field}` varchar(64) DEFAULT NULL COMMENT \'{field_comments[field]}\''
            elif field in ['证件类型', '证件编号']:
                field_def = f'`{field}` varchar(32) DEFAULT NULL COMMENT \'{field_comments[field]}\''
            else:
                field_def = f'`{field}` varchar(64) DEFAULT NULL COMMENT \'{field_comments[field]}\''
            fields_sql_parts.append(field_def)
        return ',\n'.join(fields_sql_parts)

    def batch_insert_to_temp(self, data: List[List[Any]], batch_size: int = 1000) -> int:
        """
        批量插入 ftp_临时表 临时表（分批次插入，提升大数据量处理性能）
        :param data: 待插入数据（每行17个字段）
        :param batch_size: 单次插入批次大小
        :return: 总插入行数
        """
        if not data:
            self.logger.info("无数据插入临时表（数据为空）")
            return 0
        valid_data = [row for row in data if len(row) == len(BUSINESS_FIELDS)]
        if not valid_data:
            self.logger.warning(f"无有效数据插入临时表（字段数需为{len(BUSINESS_FIELDS)}个）")
            return 0
        conn = self.get_connection()
        if not conn:
            return 0
        total_inserted = 0
        try:
            with conn.cursor() as cursor:
                cursor.execute("TRUNCATE TABLE `ftp_临时表`")
                fields_str = ', '.join(
                    [f'`{field}`' for field in BUSINESS_FIELDS])
                placeholders = ', '.join(['%s'] * len(BUSINESS_FIELDS))
                sql = f"""
                INSERT INTO `ftp_临时表` ({fields_str})
                VALUES ({placeholders})
                ON DUPLICATE KEY UPDATE `id` = `id`  # 重复数据不更新
                """
                for i in range(0, len(valid_data), batch_size):
                    batch_data = valid_data[i:i+batch_size]
                    cursor.executemany(sql, batch_data)
                    batch_inserted = cursor.rowcount
                    total_inserted += batch_inserted
                    self.logger.debug(
                        f"临时表批次{i//batch_size + 1}插入{batch_inserted}条数据")

                conn.commit()
                self.logger.info(f"ftp_临时表 共插入{total_inserted}条有效数据（已去重）")
                return total_inserted
        except MariaDBError as e:
            self.logger.error(f"插入临时表失败：{str(e)}")
            conn.rollback()
            return 0
        finally:
            if conn:
                conn.close()

    def sync_temp_to_target(self, target_table: str, year: int, month: int) -> Tuple[int, int]:
        """
        同步临时表中指定月份的数据到目标表
        :return: (插入行数, 更新行数)
        """
        if not self.ensure_target_table(target_table):
            return 0, 0

        conn = self.get_connection()
        if not conn:
            return 0, 0

        try:
            with conn.cursor() as cursor:
                fields_str = ', '.join(
                    [f'`{field}`' for field in BUSINESS_FIELDS])
                update_fields = [
                    f'`{field}` = VALUES(`{field}`)' for field in BUSINESS_FIELDS]
                update_str = ', '.join(update_fields)

                sql = f"""
                INSERT INTO `{target_table}` ({fields_str})
                SELECT {fields_str} FROM `ftp_临时表`
                WHERE YEAR(`乘车日期`) = %s AND MONTH(`乘车日期`) = %s
                ON DUPLICATE KEY UPDATE {update_str}, `更新时间` = CURRENT_TIMESTAMP
                """
                cursor.execute(sql, (year, month))
                conn.commit()
                total_affected = cursor.rowcount
                updated = total_affected // 2
                inserted = total_affected - (updated * 2)
                self.logger.info(
                    f"✅ 同步{target_table}完成：插入{inserted}条，更新{updated}条")
                return inserted, updated
        except MariaDBError as e:
            self.logger.error(f"❌ 同步{target_table}失败：{str(e)}")
            conn.rollback()
            return 0, 0
        finally:
            if conn:
                conn.close()

    def update_processed_status(self, filename: str, download_time: Union[str, datetime],
                                import_time: Union[str, datetime], data_count: int, update_count: int) -> bool:
        """
        更新文件处理状态到 ftp_更新表
        :param filename: FTP文件名
        :param download_time: 下载时间（datetime/字符串）
        :param import_time: 入库时间（datetime/字符串）
        :param data_count: 原文件总行数
        :param update_count: 入库更新量
        :return: 是否执行成功
        """
        # 参数非空校验
        if not filename:
            self.logger.error("文件名不能为空")
            return False
        if data_count < 0 or update_count < 0:
            self.logger.error("数据量/更新量不能为负数")
            return False

        # 统一时间格式为字符串
        if isinstance(download_time, datetime):
            download_time = download_time.strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(import_time, datetime):
            import_time = import_time.strftime('%Y-%m-%d %H:%M:%S')

        sql = """
        INSERT INTO `ftp_更新表` (
            `文件名`, `下载时间`, `入库时间`, `数据量`, `更新量`
        ) VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            `下载时间` = VALUES(`下载时间`),
            `入库时间` = VALUES(`入库时间`),
            `数据量` = VALUES(`数据量`),
            `更新量` = VALUES(`更新量`)
        """
        return self._execute_sql(
            sql,
            params=(filename, download_time, import_time,
                    data_count, update_count),
            commit=True
        )

    def _execute_sql(self, sql: str, params: tuple = (), commit: bool = False) -> bool:
        """
        通用SQL执行方法（参数校验+精准异常捕获）
        :return: 是否执行成功
        """
        # 严格校验参数数量
        placeholder_count = sql.count('%s')
        param_count = len(params)
        if placeholder_count != param_count:
            self.logger.error(
                f"SQL参数不匹配：占位符{placeholder_count}个，实际参数{param_count}个")
            return False

        # 空SQL校验
        if not sql.strip():
            self.logger.error("SQL语句不能为空")
            return False

        conn = None
        try:
            conn = self.get_connection()
            if not conn:
                return False

            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                if commit:
                    conn.commit()
            self.logger.debug(f"SQL执行成功：{sql}")
            return True
        except MariaDBOperationalError as e:
            self.logger.error(f"SQL执行失败（数据库连接异常）：{str(e)} | SQL: {sql}")
            if conn and commit and not self._is_sql_readonly(sql):
                conn.rollback()
        except MariaDBError as e:
            self.logger.error(
                f"SQL执行失败：{str(e)} | SQL: {sql} | Params: {params}")
            if conn and commit and not self._is_sql_readonly(sql):
                conn.rollback()
        finally:
            if conn:
                conn.close()
        return False

    def _is_sql_readonly(self, sql: str) -> bool:
        """判断SQL是否为只读操作（用于回滚判断）"""
        readonly_keywords = ['SELECT', 'SHOW', 'DESC', 'EXPLAIN', 'USE']
        return any(sql.strip().upper().startswith(kw) for kw in readonly_keywords)

    def test_connection(self) -> bool:
        """测试MariaDB连接（无需依赖业务表）"""
        conn = self.get_connection()
        if not conn:
            return False
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            self.logger.info("✅ MariaDB连接测试成功")
            return True
        except MariaDBError as e:
            self.logger.error(f"❌ MariaDB连接测试失败：{str(e)}")
            return False
        finally:
            conn.close()
