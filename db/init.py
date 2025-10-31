# encoding: utf-8

from .Proxy import Proxy
from .Fetcher import Fetcher
from fetchers import fetchers
from .conn import conn, TRANSACTION_BEGIN

def init():
    """
    初始化数据库
    """

    create_tables = Proxy.ddls + Fetcher.ddls
    for sql in create_tables:
        cur = conn.execute(sql)
        cur.close()
    conn.commit()

    # 注册所有的爬取器
    c = conn.cursor()
    c.execute(TRANSACTION_BEGIN)
    for item in fetchers:
        c.execute('SELECT * FROM fetchers WHERE name=?', (item.name,))
        if c.fetchone() is None:
            f = Fetcher()
            f.name = item.name
            c.execute('INSERT INTO fetchers VALUES(?,?,?,?,?)', f.params())
    c.close()
    conn.commit()
