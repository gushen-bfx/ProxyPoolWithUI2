# encoding: utf-8

"""
封装的数据库接口
"""

from data.config import DATABASE_PATH, DB_TYPE, DB_CONFIG
from .Proxy import Proxy
from .Fetcher import Fetcher
import datetime
import threading
import sys
import os

if DB_TYPE == 'sqlite':
    import sqlite3
elif DB_TYPE == 'mysql':
    import pymysql
elif DB_TYPE == 'postgresql':
    import psycopg2
else:
    raise ValueError(f'Unsupported database type: {DB_TYPE}')

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.ip_location import get_ip_location_cached

class CursorWrapper:
    """统一不同数据库驱动的游标行为"""

    def __init__(self, cursor, paramstyle):
        self._cursor = cursor
        self._paramstyle = paramstyle

    def _prepare(self, query, params):
        if params is None:
            return query, None

        if not isinstance(params, (tuple, list)):
            params = (params,)
        else:
            params = tuple(params)

        if self._paramstyle == 'qmark':
            return query, params

        if self._paramstyle == 'pyformat':
            if '?' in query:
                query = '%s'.join(query.split('?'))
            return query, params

        return query, params

    def execute(self, query, params=None):
        query, params = self._prepare(query, params)
        if params is None:
            self._cursor.execute(query)
        else:
            self._cursor.execute(query, params)
        return self

    def executemany(self, query, seq_of_params):
        if self._paramstyle == 'pyformat' and '?' in query:
            query = '%s'.join(query.split('?'))
        self._cursor.executemany(query, seq_of_params)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def close(self):
        self._cursor.close()

    def __iter__(self):
        return iter(self._cursor)

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return getattr(self._cursor, 'lastrowid', None)

    def __getattr__(self, item):
        return getattr(self._cursor, item)


class ConnectionWrapper:
    """简单的连接包装器，使不同数据库的用法保持一致"""

    def __init__(self, connection, paramstyle):
        self._connection = connection
        self._paramstyle = paramstyle

    def cursor(self):
        return CursorWrapper(self._connection.cursor(), self._paramstyle)

    def execute(self, query, params=None):
        cursor = self.cursor()
        cursor.execute(query, params)
        return cursor

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()

    def __getattr__(self, item):
        return getattr(self._connection, item)


def _create_connection():
    if DB_TYPE == 'sqlite':
        return sqlite3.connect(
            DATABASE_PATH,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            timeout=10.0,
            check_same_thread=False
        )
    if DB_TYPE == 'mysql':
        return pymysql.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            database=DB_CONFIG['database'],
            charset='utf8mb4',
            autocommit=False,
            connect_timeout=DB_CONFIG.get('connect_timeout', 10),
        )
    if DB_TYPE == 'postgresql':
        return psycopg2.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            dbname=DB_CONFIG['database'],
            connect_timeout=DB_CONFIG.get('connect_timeout', 10),
        )
    raise ValueError(f'Unsupported database type: {DB_TYPE}')


try:
    _raw_conn = _create_connection()
except Exception as exc:
    raise RuntimeError(f'无法连接到数据库（{DB_TYPE}）: {exc}')

PARAMSTYLE = 'qmark' if DB_TYPE == 'sqlite' else 'pyformat'
conn = ConnectionWrapper(_raw_conn, PARAMSTYLE)

if DB_TYPE == 'sqlite':
    conn.execute('PRAGMA journal_mode=WAL').close()
    conn.execute('PRAGMA synchronous=NORMAL').close()
    conn.execute('PRAGMA cache_size=10000').close()
    conn.execute('PRAGMA temp_store=MEMORY').close()
    conn.execute('PRAGMA mmap_size=268435456').close()

TRANSACTION_BEGIN = 'BEGIN EXCLUSIVE TRANSACTION' if DB_TYPE == 'sqlite' else 'BEGIN'
RANDOM_FUNCTION = 'RAND()' if DB_TYPE == 'mysql' else 'RANDOM()'
ORDER_BY_RANDOM = f'ORDER BY {RANDOM_FUNCTION}'

if DB_TYPE == 'sqlite':
    from sqlite3 import IntegrityError as DBIntegrityError  # type: ignore[attr-defined]
elif DB_TYPE == 'mysql':
    from pymysql.err import IntegrityError as DBIntegrityError  # type: ignore[attr-defined]
elif DB_TYPE == 'postgresql':
    from psycopg2 import IntegrityError as DBIntegrityError  # type: ignore[attr-defined]
else:
    DBIntegrityError = Exception

# 线程锁
conn_lock = threading.Lock()
# 进程锁
proc_lock = None

def set_proc_lock(proc_lock_sub):
    """
    设置进程锁
    proc_lock_sub : main中的进程锁
    """
    global proc_lock
    proc_lock = proc_lock_sub

def _acquire_locks():
    """
    获取所有必要的锁（线程锁和进程锁）
    """
    conn_lock.acquire()
    if proc_lock is not None:
        proc_lock.acquire()

def _release_locks():
    """
    释放所有锁
    """
    if proc_lock is not None:
        proc_lock.release()
    conn_lock.release()

def pushNewFetch(fetcher_name, protocol, ip, port, username=None, password=None, country=None, address=None):
    """
    爬取器新抓到了一个代理，调用本函数将代理放入数据库
    fetcher_name : 爬取器名称
    protocol : 代理协议
    ip : 代理IP地址
    port : 代理端口
    username : 代理账号（可选，爬取器爬到的）
    password : 代理密码（可选，爬取器爬到的）
    country : 国家（可选，爬取器爬到的）
    address : 地址（可选，爬取器爬到的）
    
    注意：如果爬取器提供了 country/address/username/password，直接写入
          如果没有提供，保持为 None，等验证成功后再获取
    """
    p = Proxy()
    p.fetcher_name = fetcher_name
    p.protocol = protocol
    p.ip = ip
    p.port = port
    p.username = username  # 由爬取器提供，可能为 None
    p.password = password  # 由爬取器提供，可能为 None
    p.country = country    # 由爬取器提供，可能为 None
    p.address = address    # 由爬取器提供，可能为 None
    
    _acquire_locks()
    
    try:
        c = conn.cursor()
        c.execute(TRANSACTION_BEGIN)
        # 更新proxies表 - 避免重复添加
        c.execute('SELECT * FROM proxies WHERE protocol=? AND ip=? AND port=?', (p.protocol, p.ip, p.port))
        row = c.fetchone()
        if row is not None: # 已经存在(protocol, ip, port) - 不重复添加，只更新部分字段
            old_p = Proxy.decode(row)
            # 更新 fetcher_name, to_validate_date，如果爬取器提供了其他信息也一并更新
            update_fields = []
            update_values = []
            
            update_fields.append('fetcher_name=?')
            update_values.append(p.fetcher_name)
            
            update_fields.append('to_validate_date=?')
            update_values.append(min(datetime.datetime.now(), old_p.to_validate_date))
            
            # 如果提供了账号密码，更新
            if username is not None:
                update_fields.append('username=?')
                update_values.append(username)
            if password is not None:
                update_fields.append('password=?')
                update_values.append(password)
            
            # 如果提供了地理位置，更新
            if country is not None:
                update_fields.append('country=?')
                update_values.append(country)
            if address is not None:
                update_fields.append('address=?')
                update_values.append(address)
            
            update_values.extend([p.protocol, p.ip, p.port])
            
            sql = f"UPDATE proxies SET {','.join(update_fields)} WHERE protocol=? AND ip=? AND port=?"
            c.execute(sql, tuple(update_values))
        else:
            # 新代理，插入所有字段
            c.execute('INSERT INTO proxies VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', p.params())
        c.close()
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        _release_locks()

def getToValidate(max_count=1):
    """
    从数据库中获取待验证的代理，根据to_validate_date字段
    优先选取已经通过了验证的代理，其次是没有通过验证的代理
    max_count : 返回数量限制
    返回 : list[Proxy]
    """
    _acquire_locks()
    c = conn.cursor()
    c.execute(TRANSACTION_BEGIN)
    c.execute('SELECT * FROM proxies WHERE to_validate_date<=? AND validated=? ORDER BY to_validate_date LIMIT ?', (
        datetime.datetime.now(),
        True,
        max_count
    ))
    proxies = [Proxy.decode(row) for row in c]
    c.execute('SELECT * FROM proxies WHERE to_validate_date<=? AND validated=? ORDER BY to_validate_date LIMIT ?', (
        datetime.datetime.now(),
        False,
        max_count - len(proxies)
    ))
    proxies = proxies + [Proxy.decode(row) for row in c]
    c.close()
    conn.commit()
    _release_locks()
    return proxies

def pushValidateResult(proxy, success, latency):
    """
    将验证器的一个结果添加进数据库中
    proxy : 代理
    success : True/False，验证是否成功
    latency : 本次验证所用的时间(单位毫秒)
    
    注意：IP可用（验证成功）且没有国家和地址信息时，会自动获取并更新
    """
    p = proxy
    should_remove = p.validate(success, latency)
    
    # 只有在验证成功（IP可用）且缺少地理位置信息时才获取
    need_update_location = False
    if success and not should_remove and (p.country is None or p.address is None):
        try:
            location = get_ip_location_cached(p.ip)
            p.country = location.get('country', '未知')
            p.address = location.get('address', '无法获取')
            need_update_location = True
            print(f"获取IP地理位置成功: {p.ip} -> {p.country}, {p.address}")
        except Exception as e:
            print(f"获取IP地理位置失败 {p.ip}: {e}")
            # 获取失败时不设置默认值，保持 None
    
    _acquire_locks()
    if should_remove:
        cur = conn.execute('DELETE FROM proxies WHERE protocol=? AND ip=? AND port=?', (p.protocol, p.ip, p.port))
        cur.close()
    else:
        # 如果需要更新地理位置信息，则包含 country 和 address
        if need_update_location:
            cur = conn.execute("""
                UPDATE proxies
                SET fetcher_name=?,validated=?,latency=?,validate_date=?,to_validate_date=?,validate_failed_cnt=?,country=?,address=?
                WHERE protocol=? AND ip=? AND port=?
            """, (
                p.fetcher_name, p.validated, p.latency, p.validate_date, p.to_validate_date, p.validate_failed_cnt,
                p.country, p.address,
                p.protocol, p.ip, p.port
            ))
            cur.close()
        else:
            # 不更新地理位置信息
            cur = conn.execute("""
                UPDATE proxies
                SET fetcher_name=?,validated=?,latency=?,validate_date=?,to_validate_date=?,validate_failed_cnt=?
                WHERE protocol=? AND ip=? AND port=?
            """, (
                p.fetcher_name, p.validated, p.latency, p.validate_date, p.to_validate_date, p.validate_failed_cnt,
                p.protocol, p.ip, p.port
            ))
            cur.close()
    conn.commit()
    _release_locks()

def getValidatedRandom(max_count):
    """
    从通过了验证的代理中，随机选择max_count个代理返回
    max_count<=0表示不做数量限制
    返回 : list[Proxy]
    
    优化：使用更快的查询方式，避免在大量数据时使用数据库的随机排序导致性能问题
    """
    _acquire_locks()
    try:
        if max_count > 0:
            # 对于有限制的查询，使用数据库提供的随机函数限制返回数量
            # 先获取总数，如果数量不多就直接随机排序，否则使用更快的方式
            r_count = conn.execute('SELECT count(*) FROM proxies WHERE validated=?', (True,))
            total = r_count.fetchone()[0]
            r_count.close()
            
            if total <= max_count * 2:
                # 数据量不大，直接随机排序
                r = conn.execute(
                    f'SELECT * FROM proxies WHERE validated=? {ORDER_BY_RANDOM} LIMIT ?',
                    (True, max_count)
                )
            else:
                # 数据量大，使用更快的方式：按 validate_date 排序（最近验证的）
                r = conn.execute('SELECT * FROM proxies WHERE validated=? ORDER BY validate_date DESC LIMIT ?', (True, max_count))
        else:
            r = conn.execute('SELECT * FROM proxies WHERE validated=? ORDER BY validate_date DESC', (True,))
        
        proxies = [Proxy.decode(row) for row in r]
        r.close()
    finally:
        _release_locks()
    return proxies
    
    #新增方法
def get_by_protocol(protocol, max_count):
    """
    查询 protocol 字段为指定值的代理服务器记录
    max_count 表示返回记录的最大数量，如果为 0 或负数则返回所有记录
    返回 : list[Proxy]
    """
    _acquire_locks()
    if max_count > 0:
        r = conn.execute(
            f'SELECT * FROM proxies WHERE protocol=? AND validated=? {ORDER_BY_RANDOM} LIMIT ?',
            (protocol, True, max_count)
        )
    else:
        r = conn.execute(
            f'SELECT * FROM proxies WHERE protocol=? AND validated=? {ORDER_BY_RANDOM}',
            (protocol, True)
        )
    proxies = [Proxy.decode(row) for row in r]
    r.close()
    _release_locks()
    return proxies

def pushFetcherResult(name, proxies_cnt):
    """
    更新爬取器的状态，每次在完成一个网站的爬取之后，调用本函数
    name : 爬取器的名称
    proxies_cnt : 本次爬取到的代理数量
    """
    _acquire_locks()
    c = conn.cursor()
    c.execute(TRANSACTION_BEGIN)
    c.execute('SELECT * FROM fetchers WHERE name=?', (name,))
    row = c.fetchone()
    if row is None:
        raise ValueError(f'ERRROR: can not find fetcher {name}')
    else:
        f = Fetcher.decode(row)
        f.last_proxies_cnt = proxies_cnt
        f.sum_proxies_cnt = f.sum_proxies_cnt + proxies_cnt
        f.last_fetch_date = datetime.datetime.now()
        c.execute('UPDATE fetchers SET sum_proxies_cnt=?,last_proxies_cnt=?,last_fetch_date=? WHERE name=?', (
            f.sum_proxies_cnt, f.last_proxies_cnt, f.last_fetch_date, f.name
        ))
    c.close()
    conn.commit()
    _release_locks()

def pushFetcherEnable(name, enable):
    """
    设置是否起用对应爬取器，被禁用的爬取器将不会被运行
    name : 爬取器的名称
    enable : True/False, 是否启用
    """
    _acquire_locks()
    c = conn.cursor()
    c.execute(TRANSACTION_BEGIN)
    c.execute('SELECT * FROM fetchers WHERE name=?', (name,))
    row = c.fetchone()
    if row is None:
        raise ValueError(f'ERRROR: can not find fetcher {name}')
    else:
        f = Fetcher.decode(row)
        f.enable = enable
        c.execute('UPDATE fetchers SET enable=? WHERE name=?', (
            f.enable, f.name
        ))
    c.close()
    conn.commit()
    _release_locks()

def getAllFetchers():
    """
    获取所有的爬取器以及状态
    返回 : list[Fetcher]
    """
    _acquire_locks()
    r = conn.execute('SELECT * FROM fetchers')
    fetchers = [Fetcher.decode(row) for row in r]
    r.close()
    _release_locks()
    return fetchers

def getFetcher(name):
    """
    获取指定爬取器以及状态
    返回 : Fetcher
    """
    _acquire_locks()
    r = conn.execute('SELECT * FROM fetchers WHERE name=?', (name,))
    row = r.fetchone()
    r.close()
    _release_locks()
    if row is None:
        return None
    else:
        return Fetcher.decode(row)

def getProxyCount(fetcher_name):
    """
    查询在数据库中有多少个由指定爬取器爬取到的代理
    fetcher_name : 爬取器名称
    返回 : int
    """
    _acquire_locks()
    r = conn.execute('SELECT count(*) FROM proxies WHERE fetcher_name=?', (fetcher_name,))
    cnt = r.fetchone()[0]
    r.close()
    _release_locks()
    return cnt

def getProxyCountAll():
    """
    一次性查询所有爬取器在数据库中的代理数量
    返回 : dict {fetcher_name: count}
    """
    _acquire_locks()
    r = conn.execute('SELECT fetcher_name, count(*) FROM proxies GROUP BY fetcher_name')
    result = {row[0]: row[1] for row in r}
    r.close()
    _release_locks()
    return result

def getProxiesStatus():
    """
    获取代理状态，包括`全部代理数量`，`当前可用代理数量`，`等待验证代理数量`
    返回 : dict
    """
    _acquire_locks()
    r = conn.execute('SELECT count(*) FROM proxies')
    sum_proxies_cnt = r.fetchone()[0]
    r.close()

    r = conn.execute('SELECT count(*) FROM proxies WHERE validated=?', (True,))
    validated_proxies_cnt = r.fetchone()[0]
    r.close()

    r = conn.execute('SELECT count(*) FROM proxies WHERE to_validate_date<=?', (datetime.datetime.now(),))
    pending_proxies_cnt = r.fetchone()[0]
    r.close()
    _release_locks()
    return dict(
        sum_proxies_cnt=sum_proxies_cnt,
        validated_proxies_cnt=validated_proxies_cnt,
        pending_proxies_cnt=pending_proxies_cnt
    )

def pushClearFetchersStatus():
    """
    清空爬取器的统计信息，包括sum_proxies_cnt,last_proxies_cnt,last_fetch_date
    """
    _acquire_locks()
    c = conn.cursor()
    c.execute(TRANSACTION_BEGIN)
    c.execute('UPDATE fetchers SET sum_proxies_cnt=?, last_proxies_cnt=?, last_fetch_date=?', (0, 0, None))
    c.close()
    conn.commit()
    _release_locks()
