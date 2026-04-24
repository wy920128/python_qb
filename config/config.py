import os
from datetime import datetime

# 目录配置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
DATA_DIR = os.path.join(BASE_DIR, "data")

# 数据库配置
DB_CONFIG = {
    "host": "10.3.32.239",
    "port": 3306,
    "user": "wangye",
    "password": "Wy025871.",
    "database": "情报",
    "autocommit": False
}

# FTP配置
FTP_CONFIG = {
    "host": "10.3.16.197",
    "user": "htwa",
    "passwd": "htwa@123",
    "remote_path": "haerbin",
    "timeout": 60,
    "file_suffix": ".txt"
}

# 业务配置（跨月分表逻辑）
today = datetime.now()
current_year = today.year
current_month = today.month

# 本月信息（表名+年份+月份）
CURRENT_MONTH_INFO = {
    "table_name": f"购票数据表_{current_year}年{current_month:02d}月",
    "year": current_year,
    "month": current_month
}

# 下月信息（支持跨年）
if current_month == 12:
  next_year = current_year + 1
  next_month = 1
else:
  next_year = current_year
  next_month = current_month + 1

NEXT_MONTH_INFO = {
    "table_name": f"购票数据表_{next_year}年{next_month:02d}月",
    "year": next_year,
    "month": next_month
}

# 目标表列表（本月+下月，适配提前15天购票）
TARGET_TABLES = [CURRENT_MONTH_INFO, NEXT_MONTH_INFO]
MAX_FILE_SIZE = 200 * 1024 * 1024  # 最大处理文件大小（200MB）

# 文件字段顺序（17个字段）
FILE_FIELDS = [
    '姓名', '证件类型', '证件编号', '乘车日期(yyyymmdd)', '乘车时间(hh:mm)', '车次', '发站', '到站',
    '车厢号', '座位号', '席别', '票号', '票种', '售票处', '窗口', '售票时间', '票价'
]

# 数据库业务字段顺序（与文件字段映射）
BUSINESS_FIELDS = [
    '车次', '乘车日期', '乘车时间', '发站', '到站', '车厢号', '座位号', '席别',
    '姓名', '证件编号', '证件类型', '售票处', '窗口', '售票时间', '票号', '票价', '票种'
]

# 字段映射关系：文件索引 → 数据库字段
FIELD_MAPPING = [
    (5, '车次'),    # 文件第6列 → 数据库车次
    (3, '乘车日期'),# 文件第4列 → 数据库乘车日期
    (4, '乘车时间'),# 文件第5列 → 数据库乘车时间
    (6, '发站'),    # 文件第7列 → 数据库发站
    (7, '到站'),    # 文件第8列 → 数据库到站
    (8, '车厢号'),  # 文件第9列 → 数据库车厢号
    (9, '座位号'),  # 文件第10列 → 数据库座位号
    (10, '席别'),   # 文件第11列 → 数据库席别
    (0, '姓名'),    # 文件第1列 → 数据库姓名
    (2, '证件编号'),# 文件第3列 → 数据库证件编号
    (1, '证件类型'),# 文件第2列 → 数据库证件类型
    (13, '售票处'), # 文件第14列 → 数据库售票处
    (14, '窗口'),   # 文件第15列 → 数据库窗口
    (15, '售票时间'),# 文件第16列 → 数据库售票时间
    (11, '票号'),   # 文件第12列 → 数据库票号
    (16, '票价'),   # 文件第17列 → 数据库票价
    (12, '票种')    # 文件第13列 → 数据库票种
]

# 非空字段列表
REQUIRED_FIELDS = ['车次', '乘车日期', '乘车时间', '发站', '到站', '售票处', '售票时间', '票号']

# 日期时间字段配置
DATE_FIELDS = ['乘车日期']  # 文件格式：yyyymmdd → 数据库格式：yyyy-mm-dd
DATETIME_FIELDS = ['售票时间']  # 格式：yyyy-mm-dd hh:mm:ss
TIME_FIELDS = ['乘车时间']  # 文件格式：hh:mm → 数据库格式：hh:mm:ss

# 全字段唯一索引（17个字段）
UNIQUE_KEY_FIELDS = [
    '姓名', '证件类型', '证件编号', '乘车日期', '乘车时间', '车次', '发站', '到站',
    '车厢号', '座位号', '席别', '票号', '票种', '售票处', '窗口', '票价'
]