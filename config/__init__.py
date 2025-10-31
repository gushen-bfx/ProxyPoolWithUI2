# encoding: utf-8
"""
Global application configuration loaded from environment variables or `.env` files.
This module lives outside the persistent data directory so that Docker bind mounts
on `/proxy/data` do not shadow the configuration code.
"""

import os
import secrets
from pathlib import Path

# -------------------------------------------------------------
# Paths
# -------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env_file() -> None:
    """Load environment variables from the project level `.env` file if present."""
    env_file = PROJECT_ROOT / '.env'
    if not env_file.exists():
        return

    try:
        for line in env_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip())
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"⚠️  加载 .env 文件失败: {exc}")


load_env_file()

DATA_DIR = Path(os.environ.get('DATA_DIR', PROJECT_ROOT / 'data')).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = str(DATA_DIR / 'data.db')

# -------------------------------------------------------------
# Database configuration
# -------------------------------------------------------------

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

# -------------------------------------------------------------
# Data files
# -------------------------------------------------------------

USERS_FILE = str(DATA_DIR / 'users.json')
API_STATUS_FILE = str(DATA_DIR / 'api_status.json')
SUBSCRIPTIONS_FILE = str(DATA_DIR / 'sub.json')

# -------------------------------------------------------------
# Runtime tunables
# -------------------------------------------------------------

PROC_FETCHER_SLEEP = 5 * 60
PROC_VALIDATOR_SLEEP = 5

VALIDATE_THREAD_NUM = 200
VALIDATE_URL = 'https://qq.com'
VALIDATE_METHOD = 'HEAD'
VALIDATE_HEADER = 'location'
VALIDATE_KEYWORD = 'www.qq.com'
VALIDATE_TIMEOUT = 5
VALIDATE_MAX_FAILS = 3

# -------------------------------------------------------------
# Authentication configuration
# -------------------------------------------------------------

JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY')

if not JWT_SECRET_KEY:
    print('=' * 60)
    print('🔴 安全警告：未找到 JWT_SECRET_KEY 配置！')
    print('=' * 60)
    print('请运行以下命令进行安全配置：')
    print('python setup_security.py')
    print('')
    print('或者手动创建 .env 文件并添加：')
    print('JWT_SECRET_KEY=your-strong-secret-key')
    print('=' * 60)
    raise ValueError('必须配置 JWT_SECRET_KEY！请运行 python setup_security.py')

if len(JWT_SECRET_KEY) < 32:
    print('=' * 60)
    print('🔴 安全警告：JWT_SECRET_KEY 长度不足！')
    print('=' * 60)
    print(f'当前长度: {len(JWT_SECRET_KEY)} 字符')
    print('建议长度: 至少 32 字符')
    print('')
    print('生成强密钥命令：')
    print("python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
    print('=' * 60)
    raise ValueError('JWT_SECRET_KEY 长度必须至少32位')

if JWT_SECRET_KEY in ['your-secret-key-change-it-in-production-2025', 'admin123', 'password', 'secret']:
    print('=' * 60)
    print('🔴 安全警告：检测到弱密钥！')
    print('=' * 60)
    print('当前密钥过于简单，存在安全风险！')
    print('请立即更换为强密钥：')
    print("python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
    print('=' * 60)
    raise ValueError('检测到弱密钥，请使用强密钥！')

print('JWT密钥配置检查通过')

TOKEN_EXPIRATION_HOURS = 24

from auth import AuthManager  # noqa: E402  # 需在常量定义之后导入以避免循环引用

auth_manager = AuthManager(
    secret_key=JWT_SECRET_KEY,
    token_expiration_hours=TOKEN_EXPIRATION_HOURS,
)


def generate_jwt_secret_key(length: int = 32) -> str:
    """生成安全的JWT密钥。"""
    return secrets.token_urlsafe(length)


def print_security_setup_guide() -> None:
    """打印安全配置指南。"""
    print('=' * 60)
    print('ProxyPoolWithUI2 安全配置指南')
    print('=' * 60)
    print('1. 运行 python setup_security.py 自动生成安全配置')
    print('2. 或者将以下内容添加到 .env 文件：')
    print('   JWT_SECRET_KEY=your-strong-secret-key')
    print('3. 建议设置 DATA_DIR 变量以自定义数据目录（可选）')
    print('=' * 60)


__all__ = [
    'PROJECT_ROOT',
    'DATA_DIR',
    'DATABASE_PATH',
    'DB_TYPE',
    'DB_CONFIG',
    'USERS_FILE',
    'API_STATUS_FILE',
    'SUBSCRIPTIONS_FILE',
    'PROC_FETCHER_SLEEP',
    'PROC_VALIDATOR_SLEEP',
    'VALIDATE_THREAD_NUM',
    'VALIDATE_URL',
    'VALIDATE_METHOD',
    'VALIDATE_HEADER',
    'VALIDATE_KEYWORD',
    'VALIDATE_TIMEOUT',
    'VALIDATE_MAX_FAILS',
    'JWT_SECRET_KEY',
    'TOKEN_EXPIRATION_HOURS',
    'auth_manager',
    'generate_jwt_secret_key',
    'print_security_setup_guide',
]
