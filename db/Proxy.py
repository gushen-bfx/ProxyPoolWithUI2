# encoding: utf-8

import datetime
import random
class Proxy(object):
    """
    代理，用于表示数据库中的一个记录
    """

    ddls = ["""
    CREATE TABLE IF NOT EXISTS proxies
    (
        fetcher_name VARCHAR(255) NOT NULL,
        protocol VARCHAR(32) NOT NULL,
        ip VARCHAR(255) NOT NULL,
        port INTEGER NOT NULL,
        validated BOOLEAN NOT NULL,
        latency INTEGER,
        validate_date TIMESTAMP NULL,
        to_validate_date TIMESTAMP NOT NULL,
        validate_failed_cnt INTEGER NOT NULL,
        created_date TIMESTAMP NOT NULL,
        country VARCHAR(100),
        address VARCHAR(255),
        username VARCHAR(100),
        password VARCHAR(100),
        PRIMARY KEY (protocol, ip, port)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS proxies_fetcher_name_index
    ON proxies(fetcher_name)
    """,
    """
    CREATE INDEX IF NOT EXISTS proxies_to_validate_date_index
    ON proxies(to_validate_date ASC)
    """]

    def __init__(self):
        self.fetcher_name = None
        self.protocol = None
        self.ip = None
        self.port = None
        self.validated = False
        self.latency = None
        self.validate_date = None
        self.to_validate_date = datetime.datetime.now()
        self.validate_failed_cnt = 0
        self.created_date = datetime.datetime.now()
        self.country = None
        self.address = None
        self.username = None  # 用户名，None表示无认证
        self.password = None  # 密码，None表示无认证
    
    def params(self):
        """
        返回一个元组，包含自身的全部属性
        """
        return (
            self.fetcher_name,
            self.protocol, self.ip, self.port,
            self.validated, self.latency,
            self.validate_date, self.to_validate_date, self.validate_failed_cnt,
            self.created_date,
            self.country, self.address, self.username, self.password
        )
    
    def to_dict(self):
        """
        返回一个dict，包含自身的全部属性
        """
        # 计算存活时间（秒）
        alive_time = None
        if self.created_date:
            alive_time = int((datetime.datetime.now() - self.created_date).total_seconds())
        
        return {
            'fetcher_name': self.fetcher_name,
            'protocol': self.protocol,
            'ip': self.ip,
            'port': self.port,
            'validated': self.validated,
            'latency': self.latency,
            'validate_date': str(self.validate_date) if self.validate_date is not None else None,
            'to_validate_date': str(self.to_validate_date) if self.to_validate_date is not None else None,
            'validate_failed_cnt': self.validate_failed_cnt,
            'created_date': str(self.created_date) if self.created_date is not None else None,
            'alive_time': alive_time,
            'country': self.country,
            'address': self.address,
            'username': self.username,
            'password': self.password
        }
    
    @staticmethod
    def decode(row):
        """
        将数据库返回的一行解析为Proxy
        row : 数据库返回的一行
        """
        # 兼容旧数据（9, 10个字段）和新数据（14个字段）
        assert len(row) in [9, 10, 14]
        p = Proxy()
        p.fetcher_name = row[0]
        p.protocol = row[1]
        p.ip = row[2]
        p.port = row[3]
        p.validated = bool(row[4])
        p.latency = row[5]
        p.validate_date = row[6]
        p.to_validate_date = row[7]
        p.validate_failed_cnt = row[8]
        
        # 处理 created_date (第10个字段)
        if len(row) >= 10:
            p.created_date = row[9] if row[9] else datetime.datetime.now()
        else:
            p.created_date = datetime.datetime.now()
        
        # 处理新增字段 (第11-14个字段)
        if len(row) >= 14:
            p.country = row[10]
            p.address = row[11]
            p.username = row[12]  # 可以为 None
            p.password = row[13]  # 可以为 None
        else:
            p.country = None
            p.address = None
            p.username = None
            p.password = None
        
        return p
    
    def validate(self, success, latency):
        """
        传入一次验证结果，根据验证结果调整自身属性，并返回是否删除这个代理
        success : True/False，表示本次验证是否成功
        返回 : True/False，True表示这个代理太差了，应该从数据库中删除
        """
        self.latency = latency
        if success: # 验证成功
            self.validated = True
            self.validate_date = datetime.datetime.now()
            self.validate_failed_cnt = 0
            #self.to_validate_date = datetime.datetime.now() + datetime.timedelta(minutes=30)  # 30分钟之后继续验证
            self.to_validate_date = datetime.datetime.now() + datetime.timedelta(minutes=random.randint(10, 60))  # 10·60分钟之后继续验证
            return False
        else:
            self.validated = False
            self.validate_date = datetime.datetime.now()
            self.validate_failed_cnt = self.validate_failed_cnt + 1

            # 验证失败的次数越多，距离下次验证的时间越长
            delay_minutes = self.validate_failed_cnt * 10
            self.to_validate_date = datetime.datetime.now() + datetime.timedelta(minutes=delay_minutes)

            if self.validate_failed_cnt >= 6:
                return True
            else:
                return False
