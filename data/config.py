# encoding: utf-8

"""
配置文件，一般来说不需要修改
如果需要启用或者禁用某些网站的爬取器，可在网页上进行配置
"""

import os
import secrets

# 尝试加载 .env 文件
def load_env_file():
    """加载 .env 文件中的环境变量"""
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(env_file):
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        os.environ[key.strip()] = value.strip()
        except Exception as e:
            print(f"⚠️  加载 .env 文件失败: {e}")

# 加载 .env 文件
load_env_file()

# 数据目录路径（当前目录就是data目录）
DATA_DIR = os.path.dirname(__file__)

# 确保数据目录存在
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# 数据库文件路径（默认使用 SQLite）
DATABASE_PATH = os.path.join(DATA_DIR, 'data.db')

# 数据库配置
_db_type_raw = os.environ.get('DB_TYPE', 'sqlite').strip().lower()
if _db_type_raw in ('sqlite', 'sqlite3'):
    DB_TYPE = 'sqlite'
elif _db_type_raw in ('mysql',):
    DB_TYPE = 'mysql'
elif _db_type_raw in ('postgresql', 'postgres', 'psql'):
    DB_TYPE = 'postgresql'
else:
    raise ValueError(f"不支持的数据库类型: {_db_type_raw}")

if DB_TYPE == 'sqlite':
    DB_CONFIG = {
        'path': DATABASE_PATH,
    }
else:
    default_port = 3306 if DB_TYPE == 'mysql' else 5432
    DB_CONFIG = {
        'host': os.environ.get('DB_HOST', 'localhost'),
        'port': int(os.environ.get('DB_PORT', default_port)),
        'user': os.environ.get('DB_USER', 'proxypool'),
        'password': os.environ.get('DB_PASSWORD', ''),
        'database': os.environ.get('DB_NAME', 'proxypool'),
        'connect_timeout': int(os.environ.get('DB_CONNECT_TIMEOUT', 10)),
    }

# 其他数据文件路径
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
API_STATUS_FILE = os.path.join(DATA_DIR, 'api_status.json')
SUBSCRIPTIONS_FILE = os.path.join(DATA_DIR, 'sub.json')

# 每次运行所有爬取器之后，睡眠多少时间，单位秒
PROC_FETCHER_SLEEP = 5 * 60

# 验证器每次睡眠的时间，单位秒
PROC_VALIDATOR_SLEEP = 5

# 验证器的配置参数
VALIDATE_THREAD_NUM = 200 # 验证线程数量
# 验证器的逻辑是：
# 使用代理访问 VALIDATE_URL 网站，超时时间设置为 VALIDATE_TIMEOUT
# 如果没有超时：
# 1、若选择的验证方式为GET：  返回的网页中包含 VALIDATE_KEYWORD 文字，那么就认为本次验证成功
# 2、若选择的验证方式为HEAD： 返回的响应头中，对于的 VALIDATE_HEADER 响应字段内容包含 VALIDATE_KEYWORD 内容，那么就认为本次验证成功
# 上述过程最多进行 VALIDATE_MAX_FAILS 次，只要有一次成功，就认为代理可用
VALIDATE_URL = 'https://qq.com'
VALIDATE_METHOD = 'HEAD' # 验证方式，可选：GET、HEAD
VALIDATE_HEADER = 'location' # 仅用于HEAD验证方式，百度响应头Server字段KEYWORD可填：bfe
VALIDATE_KEYWORD = 'www.qq.com'
VALIDATE_TIMEOUT = 5 # 超时时间，单位s
VALIDATE_MAX_FAILS = 3

# ============= 认证配置 =============

# JWT密钥 - 从 .env 文件或环境变量读取
JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY')

# 安全验证：检查JWT密钥配置
if not JWT_SECRET_KEY:
    print("=" * 60)
    print("🔴 安全警告：未找到 JWT_SECRET_KEY 配置！")
    print("=" * 60)
    print("请运行以下命令进行安全配置：")
    print("python setup_security.py")
    print("")
    print("或者手动创建 .env 文件并添加：")
    print("JWT_SECRET_KEY=your-strong-secret-key")
    print("=" * 60)
    raise ValueError("必须配置 JWT_SECRET_KEY！请运行 python setup_security.py")

# 验证密钥强度
if len(JWT_SECRET_KEY) < 32:
    print("=" * 60)
    print("🔴 安全警告：JWT_SECRET_KEY 长度不足！")
    print("=" * 60)
    print(f"当前长度: {len(JWT_SECRET_KEY)} 字符")
    print("建议长度: 至少 32 字符")
    print("")
    print("生成强密钥命令：")
    print("python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
    print("=" * 60)
    raise ValueError("JWT_SECRET_KEY 长度必须至少32位")

# 检查是否使用默认密钥（安全警告）
if JWT_SECRET_KEY in ['your-secret-key-change-it-in-production-2025', 'admin123', 'password', 'secret']:
    print("=" * 60)
    print("🔴 安全警告：检测到弱密钥！")
    print("=" * 60)
    print("当前密钥过于简单，存在安全风险！")
    print("请立即更换为强密钥：")
    print("python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
    print("=" * 60)
    raise ValueError("检测到弱密钥，请使用强密钥！")

print("JWT密钥配置检查通过")

# Token过期时间（小时）
TOKEN_EXPIRATION_HOURS = 24

# 默认管理员账户
# 首次启动会自动创建，用户名：admin，密码：admin123
# 登录后请立即修改密码

# 初始化认证管理器
from auth import AuthManager
auth_manager = AuthManager(
    secret_key=JWT_SECRET_KEY,
    token_expiration_hours=TOKEN_EXPIRATION_HOURS
)

def generate_jwt_secret_key(length=32):
    """
    生成安全的JWT密钥
    :param length: 密钥长度，默认32字符
    :return: 生成的密钥字符串
    """
    return secrets.token_urlsafe(length)

def print_security_setup_guide():
    """
    打印安全配置指南
    """
    print("\n" + "=" * 80)
    print("🔐 ProxyPool 安全配置指南")
    print("=" * 80)
    print("1. 生成强密钥：")
    print(f"   python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
    print("")
    print("2. 设置环境变量：")
    print("   Windows:")
    print("   set JWT_SECRET_KEY=your-generated-secret-key")
    print("")
    print("   Linux/Mac:")
    print("   export JWT_SECRET_KEY=your-generated-secret-key")
    print("")
    print("3. 永久设置（推荐）：")
    print("   在系统环境变量中设置 JWT_SECRET_KEY")
    print("")
    print("4. 验证配置：")
    print("   python -c \"from config import JWT_SECRET_KEY; print('密钥长度:', len(JWT_SECRET_KEY))\"")
    print("=" * 80)