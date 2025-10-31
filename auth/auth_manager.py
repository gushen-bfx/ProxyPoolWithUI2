# encoding: utf-8

import jwt
import datetime
import hashlib
import os
import json
from functools import wraps
from flask import request, jsonify
from config import USERS_FILE

class AuthManager:
    """
    认证管理器 - 处理用户认证、JWT生成和验证
    """
    
    def __init__(self, secret_key, token_expiration_hours=24):
        """
        初始化认证管理器
        :param secret_key: JWT签名密钥
        :param token_expiration_hours: Token过期时间（小时）
        """
        self.secret_key = secret_key
        self.token_expiration_hours = token_expiration_hours
        self.users_file = USERS_FILE
        self._init_users_file()
    
    def _init_users_file(self):
        """初始化用户文件，如果不存在则创建默认管理员账户"""
        if not os.path.exists(self.users_file):
            default_users = {
                "admin": {
                    "password": self._hash_password("admin123"),
                    "role": "admin",
                    "created_at": datetime.datetime.now().isoformat()
                }
            }
            with open(self.users_file, 'w', encoding='utf-8') as f:
                json.dump(default_users, f, indent=2, ensure_ascii=False)
            print(f"[Auth] 创建默认管理员账户: admin / admin123")
    
    def _hash_password(self, password):
        """对密码进行哈希"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def _load_users(self):
        """加载用户数据"""
        try:
            with open(self.users_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[Auth] 加载用户数据失败: {e}")
            return {}
    
    def _save_users(self, users):
        """保存用户数据"""
        try:
            with open(self.users_file, 'w', encoding='utf-8') as f:
                json.dump(users, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[Auth] 保存用户数据失败: {e}")
            return False
    
    def authenticate(self, username, password):
        """
        验证用户名和密码
        :param username: 用户名
        :param password: 密码（明文）
        :return: 验证成功返回用户信息，失败返回None
        """
        users = self._load_users()
        user = users.get(username)
        
        if not user:
            return None
        
        if user['password'] == self._hash_password(password):
            return {
                'username': username,
                'role': user.get('role', 'user')
            }
        
        return None
    
    def generate_token(self, username, role='user'):
        """
        生成JWT Token
        :param username: 用户名
        :param role: 用户角色
        :return: JWT Token字符串
        """
        payload = {
            'username': username,
            'role': role,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=self.token_expiration_hours),
            'iat': datetime.datetime.utcnow()
        }
        
        token = jwt.encode(payload, self.secret_key, algorithm='HS256')
        return token
    
    def verify_token(self, token):
        """
        验证JWT Token
        :param token: JWT Token字符串
        :return: 验证成功返回payload，失败返回None
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=['HS256'])
            return payload
        except jwt.ExpiredSignatureError:
            print("[Auth] Token已过期")
            return None
        except jwt.InvalidTokenError as e:
            print(f"[Auth] Token无效: {e}")
            return None
    
    def create_user(self, username, password, role='user'):
        """
        创建新用户
        :param username: 用户名
        :param password: 密码（明文）
        :param role: 用户角色
        :return: 成功返回True，失败返回False
        """
        users = self._load_users()
        
        if username in users:
            return False
        
        users[username] = {
            'password': self._hash_password(password),
            'role': role,
            'created_at': datetime.datetime.now().isoformat()
        }
        
        return self._save_users(users)
    
    def change_password(self, username, old_password, new_password):
        """
        修改用户密码
        :param username: 用户名
        :param old_password: 旧密码
        :param new_password: 新密码
        :return: 成功返回True，失败返回False
        """
        users = self._load_users()
        user = users.get(username)
        
        if not user:
            return False
        
        if user['password'] != self._hash_password(old_password):
            return False
        
        user['password'] = self._hash_password(new_password)
        user['password_changed_at'] = datetime.datetime.now().isoformat()
        
        return self._save_users(users)
    
    def delete_user(self, username):
        """
        删除用户
        :param username: 用户名
        :return: 成功返回True，失败返回False
        """
        if username == 'admin':
            return False  # 不允许删除管理员账户
        
        users = self._load_users()
        
        if username not in users:
            return False
        
        del users[username]
        return self._save_users(users)
    
    def list_users(self):
        """
        列出所有用户（不包含密码）
        :return: 用户列表
        """
        users = self._load_users()
        result = []
        
        for username, info in users.items():
            result.append({
                'username': username,
                'role': info.get('role', 'user'),
                'created_at': info.get('created_at', '')
            })
        
        return result

def token_required(f):
    """
    装饰器：要求请求必须带有有效的JWT Token
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 从请求头获取token
        token = request.headers.get('Authorization')
        
        if not token:
            return jsonify({
                'success': False,
                'message': '缺少认证Token',
                'error': 'MISSING_TOKEN'
            }), 401
        
        # 移除 "Bearer " 前缀
        if token.startswith('Bearer '):
            token = token[7:]
        
        # 验证token
        from config import auth_manager
        payload = auth_manager.verify_token(token)
        
        if not payload:
            return jsonify({
                'success': False,
                'message': 'Token无效或已过期',
                'error': 'INVALID_TOKEN'
            }), 401
        
        # 将用户信息添加到请求上下文
        request.user = payload
        
        return f(*args, **kwargs)
    
    return decorated_function

