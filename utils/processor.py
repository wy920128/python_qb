import os
import re
import traceback
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from config.settings import (
    DATA_DIR, FILE_FIELDS, FIELD_MAPPING, REQUIRED_FIELDS, MAX_FILE_SIZE
)
from core.database import DatabaseHandler
from utils.logger import LogManager

class DataProcessor:
    """数据处理器（适配跨月双表同步）"""
    def __init__(self, db_handler: DatabaseHandler, logger: LogManager):
        self.db_handler = db_handler
        self.logger = logger

    def process_file(self, filename: str, target_tables: List[Dict[str, Any]]) -> Tuple[int, int]:
        """处理单个文件：解析→临时表→双目标表同步"""
        file_path = os.path.join(DATA_DIR, filename)
        total_inserted = 0  # 双表合计插入数
        total_updated = 0    # 双表合计更新数

        try:
            # 1. 文件合法性校验
            if not os.path.exists(file_path):
                self.logger.error(f"文件{filename}不存在，跳过处理")
                return 0, 0, 0
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                self.logger.warning(f"文件{filename}为空，跳过处理")
                return 0, 0, 0
            if file_size > MAX_FILE_SIZE:
                self.logger.error(f"文件{filename}超过200MB限制，跳过处理")
                return 0, 0, 0

            # 2. 解析文件数据
            self.logger.info(f"开始处理文件：{filename}（大小：{file_size/1024/1024:.1f}MB）")
            processed_data, total_lines = self._read_and_process_file(file_path)
            if not processed_data:
                self.logger.warning(f"文件{filename}无有效数据，跳过插入")
                return 0, 0, 0
            self.logger.info(f"文件解析完成：去重后剩余{len(processed_data)}条有效数据")

            # 3. 插入临时表
            temp_inserted = self.db_handler.batch_insert_to_temp(processed_data)
            if temp_inserted == 0:
                self.logger.warning(f"无数据插入临时表，跳过同步")
                return 0, 0, 0

            # 4. 同步到本月表和下月表
            for table_info in target_tables:
                table_name = table_info["table_name"]
                year = table_info["year"]
                month = table_info["month"]
                self.logger.info(f"\n--- 开始同步{table_name}（{year}年{month}月）---")
                inserted, updated = self.db_handler.sync_temp_to_target(table_name, year, month)
                total_inserted += inserted
                total_updated += updated

            self.logger.info(f"\n📊 文件{filename}处理完成：累计插入{total_inserted}条，累计更新{total_updated}条")
            return total_lines, total_inserted, total_updated
        except Exception as e:
            self.logger.error(f"❌ 文件{filename}处理失败：{str(e)}")
            traceback.print_exc()
            return 0, total_inserted, total_updated

    def _read_and_process_file(self, file_path: str) -> List[List[Any]]:
        """读取文件：编码处理+字段映射+格式转换+去重"""
        unique_data = set()
        total_lines = 0
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line_num, line in enumerate(f, 1):
                total_lines = line_num
                line = line.strip()
                if not line:
                    continue
                parts = line.split(',')
                if len(parts) != len(FILE_FIELDS):
                    self.logger.warning(f"行{line_num}字段数不匹配（实际{len(parts)}个，预期{len(FILE_FIELDS)}个）：{line[:50]}...")
                    continue
                db_row = self._map_and_convert_fields(parts, line_num)
                if not db_row:
                    continue
                unique_data.add(tuple(db_row))

        return [list(item) for item in unique_data], total_lines

    def _map_and_convert_fields(self, file_parts: List[str], line_num: int) -> Optional[List[Any]]:
        """字段映射+格式转换"""
        db_row = []
        file_data = {field: value.strip() for field, value in zip(FILE_FIELDS, file_parts)}

        for file_idx, db_field in FIELD_MAPPING:
            value = file_data[FILE_FIELDS[file_idx]]

            # 非空字段校验
            if db_field in REQUIRED_FIELDS and not value:
                self.logger.warning(f"行{line_num}字段[{db_field}]为空（必填项），跳过该条")
                return None

            # 格式转换
            try:
                if db_field == '乘车日期':
                    # yyyymmdd → yyyy-mm-dd
                    if len(value) == 8 and value.isdigit():
                        date_str = f"{value[:4]}-{value[4:6]}-{value[6:8]}"
                        datetime.strptime(date_str, '%Y-%m-%d')
                        db_row.append(date_str)
                    else:
                        raise ValueError(f"需为8位数字")
                elif db_field == '乘车时间':
                    # hh:mm 或 4位数字 → hh:mm:ss
                    if ':' in value:
                        time_str = f"{value}:00"
                        datetime.strptime(time_str, '%H:%M:%S')
                        db_row.append(time_str)
                    elif len(value) == 4 and value.isdigit():
                        hour = int(value[:2])
                        minute = int(value[2:])
                        if 0 <= hour <= 23 and 0 <= minute <= 59:
                            time_str = f"{hour}:{minute}:00"
                            db_row.append(time_str)
                        else:
                            raise ValueError(f"时间范围无效")
                    else:
                        raise ValueError(f"格式错误")
                elif db_field == '售票时间':
                    # 支持 yyyy/mm/dd hh:mm:ss.sss 或 纯数字格式
                    value_clean = value.replace('/', '-').split('.')[0]
                    try:
                        datetime.strptime(value_clean, '%Y-%m-%d %H:%M:%S')
                        db_row.append(value_clean)
                    except:
                        value_no_space = re.sub(r'[^0-9]', '', value_clean)
                        if len(value_no_space) == 14:
                            time_str = f"{value_no_space[:4]}-{value_no_space[4:6]}-{value_no_space[6:8]} {value_no_space[8:10]}:{value_no_space[10:12]}:{value_no_space[12:14]}"
                            db_row.append(time_str)
                        else:
                            raise ValueError(f"格式错误")
                elif db_field == '票价':
                    # 票价除以10，保留2位小数
                    db_row.append(round(float(value)/10, 2) if value else None)
                else:
                    # 其他字段：空值→None
                    db_row.append(value if value else None)
            except ValueError as e:
                self.logger.warning(f"行{line_num}字段[{db_field}]无效（值：{value}，错误：{str(e)}），跳过该条")
                return None

        return db_row