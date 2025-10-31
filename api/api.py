# encoding: utf-8

import os
import logging
import yaml
import datetime
import json
import jwt
import hashlib
import time
import urllib.parse
import base64
from flask import Flask
from flask import jsonify, request, redirect, send_from_directory, Response

log = logging.getLogger('werkzeug')
log.disabled = True

try:
    from db import conn
    from config import auth_manager, API_STATUS_FILE, SUBSCRIPTIONS_FILE
    from auth.auth_manager import token_required
except:
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    from db import conn
    from config import auth_manager, API_STATUS_FILE, SUBSCRIPTIONS_FILE
    from auth.auth_manager import token_required

STATIC_FOLDER = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'frontend', 'deployment', 'public')

app = Flask(
    __name__,
    static_url_path='/web',
    static_folder=STATIC_FOLDER
)

############# 认证相关接口 ################

# 登录接口 - 优化版本，提供优先级处理
@app.route('/auth/login', methods=['POST'])
def login():
    """
    用户登录接口 - 优化版本
    请求体: {"username": "admin", "password": "admin123"}
    返回: {"success": true, "token": "...", "user": {...}}
    
    优化措施：
    1. 使用独立的数据库连接，避免锁竞争
    2. 添加超时保护
    3. 优化错误处理
    """
    import time
    start_time = time.time()
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'message': '请提供用户名和密码'
            }), 400
        
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
        if not username or not password:
            return jsonify({
                'success': False,
                'message': '用户名和密码不能为空'
            }), 400
        
        # 验证用户 - 登录不需要访问数据库，直接使用文件验证
        # 这样可以避免任何数据库锁竞争问题
        user = auth_manager.authenticate(username, password)
        
        if not user:
            elapsed = time.time() - start_time
            print(f"[Login] 用户 {username} 登录失败 (耗时: {elapsed:.2f}秒)")
            return jsonify({
                'success': False,
                'message': '用户名或密码错误'
            }), 401
        
        # 生成Token
        token = auth_manager.generate_token(user['username'], user['role'])
        
        elapsed = time.time() - start_time
        print(f"[Login] 用户 {username} 登录成功 (耗时: {elapsed:.2f}秒)")
        
        return jsonify({
            'success': True,
            'message': '登录成功',
            'token': token,
            'user': {
                'username': user['username'],
                'role': user['role']
            }
        })
    
    except Exception as e:
        import traceback
        elapsed = time.time() - start_time
        print(f"[Login] 登录异常 (耗时: {elapsed:.2f}秒): {e}")
        print(traceback.format_exc())
        return jsonify({
            'success': False,
            'message': f'登录失败: {str(e)}'
        }), 500

# 验证Token接口
@app.route('/auth/verify', methods=['GET'])
@token_required
def verify_token():
    """
    验证Token是否有效
    需要在请求头中携带: Authorization: Bearer <token>
    返回: {"success": true, "user": {...}}
    """
    return jsonify({
        'success': True,
        'user': request.user
    })

# 登录性能监控接口
@app.route('/auth/status', methods=['GET'])
def auth_status():
    """
    获取认证系统状态，用于诊断登录性能问题
    返回: {"success": true, "status": {...}}
    """
    import time
    start_time = time.time()
    
    try:
        # 检查数据库连接状态
        db_status = "正常"
        db_response_time = 0
        
        try:
            db_start = time.time()
            # 简单的数据库查询测试
            from db import conn
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
            cursor.fetchone()
            cursor.close()
            db_response_time = time.time() - db_start
        except Exception as e:
            db_status = f"异常: {str(e)}"
            db_response_time = -1
        
        # 检查代理爬取和验证进程状态
        proxy_status = conn.getProxiesStatus()
        
        # 检查当前数据库锁状态
        lock_status = "未知"
        try:
            # 尝试获取锁，如果立即成功说明没有锁竞争
            if conn_lock.acquire(blocking=False):
                conn_lock.release()
                lock_status = "无锁竞争"
            else:
                lock_status = "存在锁竞争"
        except:
            lock_status = "无法检测"
        
        total_time = time.time() - start_time
        
        return jsonify({
            'success': True,
            'status': {
                'timestamp': time.time(),
                'total_response_time': round(total_time, 3),
                'database': {
                    'status': db_status,
                    'response_time': round(db_response_time, 3)
                },
                'lock_status': lock_status,
                'proxy_status': proxy_status,
                'recommendations': _get_performance_recommendations(proxy_status, db_response_time)
            }
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'获取状态失败: {str(e)}'
        }), 500

# 网络性能测试接口
@app.route('/auth/ping', methods=['GET'])
def auth_ping():
    """
    简单的网络性能测试接口，用于诊断网络延迟问题
    返回: {"success": true, "ping_time": 0.xxx}
    """
    import time
    start_time = time.time()
    
    # 简单的计算操作，测试服务器响应速度
    test_data = {
        'timestamp': time.time(),
        'test_string': 'ping_test_' + str(int(time.time() * 1000)),
        'random_number': hash(str(time.time())) % 10000
    }
    
    ping_time = time.time() - start_time
    
    return jsonify({
        'success': True,
        'ping_time': round(ping_time, 4),
        'server_time': time.time(),
        'test_data': test_data,
        'message': f'服务器响应时间: {round(ping_time * 1000, 2)}ms'
    })

def _get_performance_recommendations(proxy_status, db_response_time):
    """根据系统状态提供性能优化建议"""
    recommendations = []
    
    if db_response_time > 1.0:
        recommendations.append("数据库响应较慢，建议检查数据库性能")
    
    if proxy_status.get('pending_proxies_cnt', 0) > 1000:
        recommendations.append("待验证代理数量过多，可能影响系统性能")
    
    if proxy_status.get('validated_proxies_cnt', 0) > 10000:
        recommendations.append("已验证代理数量较多，建议定期清理无效代理")
    
    if not recommendations:
        recommendations.append("系统运行正常")
    
    return recommendations

# 修改密码接口
@app.route('/auth/change_password', methods=['POST'])
@token_required
def change_password():
    """
    修改密码接口
    请求体: {"old_password": "...", "new_password": "..."}
    """
    try:
        data = request.get_json()
        
        old_password = data.get('old_password', '')
        new_password = data.get('new_password', '')
        
        if not old_password or not new_password:
            return jsonify({
                'success': False,
                'message': '旧密码和新密码不能为空'
            }), 400
        
        if len(new_password) < 6:
            return jsonify({
                'success': False,
                'message': '新密码长度不能少于6位'
            }), 400
        
        username = request.user['username']
        
        success = auth_manager.change_password(username, old_password, new_password)
        
        if success:
            print(f"[Auth] 用户 {username} 修改密码成功")
            return jsonify({
                'success': True,
                'message': '密码修改成功，请重新登录'
            })
        else:
            return jsonify({
                'success': False,
                'message': '旧密码错误'
            }), 400
    
    except Exception as e:
        import traceback
        print(f"[Auth] 修改密码异常: {e}")
        print(traceback.format_exc())
        return jsonify({
            'success': False,
            'message': f'修改密码失败: {str(e)}'
        }), 500

############# 以下API可用于获取代理 ################

# API接口状态检查装饰器
def api_enabled_required(f):
    """API启用状态检查装饰器"""
    def decorated_function(*args, **kwargs):
        # 获取当前请求的路径
        api_path = request.path
        if not check_api_enabled(api_path):
            return jsonify({
                'success': False,
                'message': f'API接口 {api_path} 已被禁用',
                'error_code': 'API_DISABLED'
            }), 403
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# 可用于测试API状态
@app.route('/ping', methods=['GET'])
def ping():
    return 'API OK'


# 随机获取一个可用代理，如果没有可用代理则返回空白
@app.route('/fetch_random', methods=['GET'])
@api_enabled_required
@token_required
def fetch_random():
    proxies = conn.getValidatedRandom(1)
    if len(proxies) > 0:
        p = proxies[0]
        return f'{p.protocol}://{p.ip}:{p.port}'
    else:
        return ''

############# 新增加接口int ################        

#api 获取协议为http的一条结果
@app.route('/fetch_http', methods=['GET'])
@token_required
def fetch_http():
    proxies =conn.get_by_protocol('http', 1)
    if len(proxies) > 0:
        p = proxies[0]
        return f'{p.protocol}://{p.ip}:{p.port}'
    else:
        return ''

#api 获取协议为http的全部结果
@app.route('/fetch_http_all', methods=['GET'])
@token_required
def fetch_http_all():
    proxies = conn.get_by_protocol('http', -1)
    if len(proxies) == 1:
        p = proxies[0]
        return f'{p.protocol}://{p.ip}:{p.port}'
    elif len(proxies) > 1:
        proxy_list = []
        for p in proxies:
            proxy_list.append(f'{p.protocol}://{p.ip}:{p.port}')
        return ','.join(proxy_list)
    else:
        return ''
        
#api 获取协议为https的一条结果
@app.route('/fetch_https', methods=['GET'])
@token_required
def fetch_https():
    proxies =conn.get_by_protocol('https', 1)
    if len(proxies) > 0:
        p = proxies[0]
        return f'{p.protocol}://{p.ip}:{p.port}'
    else:
        return ''

#api 获取协议为https的全部结果
@app.route('/fetch_https_all', methods=['GET'])
@token_required
def fetch_https_all():
    proxies = conn.get_by_protocol('https', -1)
    if len(proxies) == 1:
        p = proxies[0]
        return f'{p.protocol}://{p.ip}:{p.port}'
    elif len(proxies) > 1:
        proxy_list = []
        for p in proxies:
            proxy_list.append(f'{p.protocol}://{p.ip}:{p.port}')
        return ','.join(proxy_list)
    else:
        return ''
                
#api 获取协议为socks4的一条结果
@app.route('/fetch_socks4', methods=['GET'])
@token_required
def fetch_socks4():
    proxies =conn.get_by_protocol('socks4', 1)
    if len(proxies) > 0:
        p = proxies[0]
        return f'{p.protocol}://{p.ip}:{p.port}'
    else:
        return ''

#api 获取协议为socks4的全部结果
@app.route('/fetch_socks4_all', methods=['GET'])
@token_required
def fetch_socks4_all():
    proxies = conn.get_by_protocol('socks4', -1)
    if len(proxies) == 1:
        p = proxies[0]
        return f'{p.protocol}://{p.ip}:{p.port}'
    elif len(proxies) > 1:
        proxy_list = []
        for p in proxies:
            proxy_list.append(f'{p.protocol}://{p.ip}:{p.port}')
        return ','.join(proxy_list)
    else:
        return ''
        
#api 获取协议为socks5的一条结果
@app.route('/fetch_socks5', methods=['GET'])
@token_required
def fetch_socks5():
    proxies =conn.get_by_protocol('socks5', 1)
    if len(proxies) > 0:
        p = proxies[0]
        return f'{p.protocol}://{p.ip}:{p.port}'
    else:
        return ''

#api 获取协议为socks5的全部结果
@app.route('/fetch_socks5_all', methods=['GET'])
@token_required
def fetch_socks5_all():
    proxies = conn.get_by_protocol('socks5', -1)
    if len(proxies) == 1:
        p = proxies[0]
        return f'{p.protocol}://{p.ip}:{p.port}'
    elif len(proxies) > 1:
        proxy_list = []
        for p in proxies:
            proxy_list.append(f'{p.protocol}://{p.ip}:{p.port}')
        return ','.join(proxy_list)
    else:
        return ''
                        
############# 新增加接口end ################    

# 获取所有可用代理，如果没有可用代理则返回空白
@app.route('/fetch_all', methods=['GET'])
@token_required
def fetch_all():
    proxies = conn.getValidatedRandom(-1)
    proxies = [f'{p.protocol}://{p.ip}:{p.port}' for p in proxies]
    return ','.join(proxies)

############# Clash 订阅接口 ################

# Clash 订阅接口 - 完整配置
@app.route('/clash', methods=['GET'])
@api_enabled_required
def clash_subscribe():
    """
    返回 Clash 订阅配置（YAML 格式）
    支持参数：
    - username: 用户名（必填）
    - password: 密码（必填）
    - c: 按国家筛选，多个国家用逗号分隔 (如: c=CN,US)
    - nc: 排除指定国家 (如: nc=CN)
    - protocol: 筛选协议类型（http/https/socks5）
    - limit: 限制代理数量，默认返回全部
    """
    try:
        # URL 参数认证
        username = request.args.get('username')
        password = request.args.get('password')
        
        if not username or not password:
            return jsonify({
                'success': False,
                'message': 'Clash 订阅需要认证，请提供 username 和 password 参数'
            }), 401
        
        # 验证账号密码
        user = auth_manager.authenticate(username, password)
        if not user:
            return jsonify({
                'success': False,
                'message': '用户名或密码错误'
            }), 401
        
        
        # 获取查询参数
        countries = request.args.get('c', '').upper().split(',') if request.args.get('c') else None
        exclude_countries = request.args.get('nc', '').upper().split(',') if request.args.get('nc') else None
        protocol = request.args.get('protocol', None)
        limit = request.args.get('limit', -1, type=int)
        
        
        # 从数据库获取代理
        if protocol:
            proxies = conn.get_by_protocol(protocol, limit)
        else:
            proxies = conn.getValidatedRandom(limit)
        
        # 按国家筛选
        if countries and countries != ['']:
            # 简单的国家代码映射
            country_map = {
                'CN': '中国', 'HK': '香港', 'TW': '台湾',
                'US': '美国', 'CA': '加拿大',
                'JP': '日本', 'SG': '新加坡',
                'AU': '澳大利亚', 'RU': '俄罗斯',
                'CH': '瑞士', 'DE': '德国', 'FR': '法国',
                'GB': '英国', 'NL': '荷兰'
            }
            country_names = [country_map.get(c, c) for c in countries if c]
            proxies = [p for p in proxies if p.country in country_names]
        
        # 排除指定国家
        if exclude_countries and exclude_countries != ['']:
            country_map = {
                'CN': '中国', 'HK': '香港', 'TW': '台湾',
                'US': '美国', 'CA': '加拿大',
                'JP': '日本', 'SG': '新加坡',
                'AU': '澳大利亚', 'RU': '俄罗斯',
                'CH': '瑞士', 'DE': '德国', 'FR': '法国',
                'GB': '英国', 'NL': '荷兰'
            }
            exclude_names = [country_map.get(c, c) for c in exclude_countries if c]
            proxies = [p for p in proxies if p.country not in exclude_names]
        
        if not proxies:
            return Response('# 暂无可用代理\nproxies: []\n', mimetype='text/yaml; charset=utf-8')
        
        # 构建完整的 Clash 配置
        clash_config = {
            'port': 7890,
            'socks-port': 7891,
            'allow-lan': False,
            'mode': 'rule',
            'log-level': 'info',
            'external-controller': '127.0.0.1:9090',
            'proxies': []
        }
        
        # 将代理转换为 Clash 格式
        proxy_names = []
        
        # 扩展的国家 emoji 映射表
        country_emoji_map = {
            '中国': '🇨🇳', '香港': '🇭🇰', '台湾': '🇹🇼',
            '美国': '🇺🇸', '加拿大': '🇨🇦',
            '日本': '🇯🇵', '新加坡': '🇸🇬',
            '澳大利亚': '🇦🇺', '俄罗斯': '🇷🇺', '俄罗斯联邦': '🇷🇺',
            '瑞士': '🇨🇭', '德国': '🇩🇪', '法国': '🇫🇷',
            '英国': '🇬🇧', '荷兰': '🇳🇱',
            '韩国': '🇰🇷', '印度': '🇮🇳', '泰国': '🇹🇭',
            '越南': '🇻🇳', '菲律宾': '🇵🇭', '印尼': '🇮🇩', '印度尼西亚': '🇮🇩',
            '马来西亚': '🇲🇾', '巴西': '🇧🇷', '阿根廷': '🇦🇷',
            '墨西哥': '🇲🇽', '智利': '🇨🇱', '哥伦比亚': '🇨🇴',
            '西班牙': '🇪🇸', '意大利': '🇮🇹', '波兰': '🇵🇱',
            '土耳其': '🇹🇷', '以色列': '🇮🇱', '阿联酋': '🇦🇪',
            '南非': '🇿🇦', '埃及': '🇪🇬', '尼日利亚': '🇳🇬',
            '乌克兰': '🇺🇦', '罗马尼亚': '🇷🇴', '捷克': '🇨🇿',
            '希腊': '🇬🇷', '葡萄牙': '🇵🇹', '瑞典': '🇸🇪',
            '挪威': '🇳🇴', '丹麦': '🇩🇰', '芬兰': '🇫🇮',
            '奥地利': '🇦🇹', '比利时': '🇧🇪', '爱尔兰': '🇮🇪',
            '阿尔巴尼亚': '🇦🇱', '保加利亚': '🇧🇬', '塞尔维亚': '🇷🇸',
            '克罗地亚': '🇭🇷', '匈牙利': '🇭🇺', '斯洛伐克': '🇸🇰',
            '斯洛文尼亚': '🇸🇮', '立陶宛': '🇱🇹', '拉脱维亚': '🇱🇻',
            '爱沙尼亚': '🇪🇪', '乌拉圭': '🇺🇾', '巴拉圭': '🇵🇾',
            '新西兰': '🇳🇿', '巴基斯坦': '🇵🇰', '孟加拉国': '🇧🇩'
        }
        
        for p in proxies:
            # 生成代理名称
            if p.country and p.country.strip() and p.country.strip() != '未知':
                # 有国家信息：显示国旗+国家+IP
                country_name = p.country.strip()
                country_emoji = country_emoji_map.get(country_name, '🌍')
                proxy_name = f'{country_emoji} {country_name}_{p.ip}'
            else:
                # 没有国家信息：只显示IP+端口
                proxy_name = f'{p.ip}_{p.port}'
            
            if p.protocol in ['http', 'https']:
                proxy_node = {
                    'name': proxy_name,
                    'type': 'http',
                    'server': p.ip,
                    'port': p.port
                }
                if p.username and p.password:
                    proxy_node['username'] = p.username
                    proxy_node['password'] = p.password
                    
            elif p.protocol == 'socks5':
                proxy_node = {
                    'name': proxy_name,
                    'type': 'socks5',
                    'server': p.ip,
                    'port': p.port
                }
                if p.username and p.password:
                    proxy_node['username'] = p.username
                    proxy_node['password'] = p.password
            else:
                continue
            
            clash_config['proxies'].append(proxy_node)
            proxy_names.append(proxy_name)
        
        if not clash_config['proxies']:
            return Response('# 暂无支持的代理类型（需要 http/https/socks5）\nproxies: []\n', 
                          mimetype='text/yaml; charset=utf-8')
        
        # 添加代理组
        clash_config['proxy-groups'] = [
            {
                'name': '全局选择',
                'type': 'select',
                'proxies': ['延迟最低', '负载均衡', '失败切换'] + proxy_names[:50]  # 只显示前50个以避免太长
            },
            {
                'name': '延迟最低',
                'type': 'url-test',
                'proxies': proxy_names,
                'url': 'http://www.gstatic.com/generate_204',
                'interval': 300
            },
            {
                'name': '负载均衡',
                'type': 'load-balance',
                'proxies': proxy_names,
                'url': 'http://www.gstatic.com/generate_204',
                'interval': 300
            },
            {
                'name': '失败切换',
                'type': 'fallback',
                'proxies': proxy_names,
                'url': 'http://www.gstatic.com/generate_204',
                'interval': 300
            }
        ]
        
        # 添加基本规则
        clash_config['rules'] = [
            'DOMAIN-SUFFIX,local,DIRECT',
            'IP-CIDR,127.0.0.0/8,DIRECT',
            'IP-CIDR,192.168.0.0/16,DIRECT',
            'IP-CIDR,10.0.0.0/8,DIRECT',
            'IP-CIDR,172.16.0.0/12,DIRECT',
            'GEOIP,CN,DIRECT',
            'MATCH,全局选择'
        ]
        
        # 转换为 YAML 格式
        yaml_content = yaml.dump(clash_config, 
                                allow_unicode=True, 
                                default_flow_style=False,
                                sort_keys=False)
        
        # 添加注释头
        header = f"""# ProxyPool Clash 订阅配置
# 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# 代理数量: {len(clash_config['proxies'])}
# 项目地址: https://github.com/huppugo1/ProxyPoolWithUI

"""
        
        return Response(header + yaml_content, mimetype='text/yaml; charset=utf-8')
        
    except Exception as e:
        error_msg = f'# 生成 Clash 配置失败: {str(e)}\n'
        return Response(error_msg, mimetype='text/yaml; charset=utf-8', status=500)

# Clash 订阅接口 - 仅代理列表
@app.route('/clash/proxies', methods=['GET'])
def clash_proxies():
    """
    返回 Clash 代理节点列表（YAML 格式）
    支持参数：
    - username: 用户名（必填）
    - password: 密码（必填）
    - c: 按国家筛选，多个国家用逗号分隔 (如: c=CN,US)
    - nc: 排除指定国家 (如: nc=CN)
    - protocol: 筛选协议类型（http/https/socks5）
    - limit: 限制代理数量，默认返回全部
    """
    try:
        # URL 参数认证
        username = request.args.get('username')
        password = request.args.get('password')
        
        if not username or not password:
            return jsonify({
                'success': False,
                'message': 'Clash 订阅需要认证，请提供 username 和 password 参数'
            }), 401
        
        # 验证账号密码
        user = auth_manager.authenticate(username, password)
        if not user:
            return jsonify({
                'success': False,
                'message': '用户名或密码错误'
            }), 401
        
        
        # 获取查询参数
        countries = request.args.get('c', '').upper().split(',') if request.args.get('c') else None
        exclude_countries = request.args.get('nc', '').upper().split(',') if request.args.get('nc') else None
        protocol = request.args.get('protocol', None)
        limit = request.args.get('limit', -1, type=int)
        
        
        # 从数据库获取代理
        if protocol:
            proxies = conn.get_by_protocol(protocol, limit)
        else:
            proxies = conn.getValidatedRandom(limit)
        
        # 按国家筛选
        if countries and countries != ['']:
            country_map = {
                'CN': '中国', 'HK': '香港', 'TW': '台湾',
                'US': '美国', 'CA': '加拿大',
                'JP': '日本', 'SG': '新加坡',
                'AU': '澳大利亚', 'RU': '俄罗斯',
                'CH': '瑞士', 'DE': '德国', 'FR': '法国',
                'GB': '英国', 'NL': '荷兰'
            }
            country_names = [country_map.get(c, c) for c in countries if c]
            proxies = [p for p in proxies if p.country in country_names]
        
        # 排除指定国家
        if exclude_countries and exclude_countries != ['']:
            country_map = {
                'CN': '中国', 'HK': '香港', 'TW': '台湾',
                'US': '美国', 'CA': '加拿大',
                'JP': '日本', 'SG': '新加坡',
                'AU': '澳大利亚', 'RU': '俄罗斯',
                'CH': '瑞士', 'DE': '德国', 'FR': '法国',
                'GB': '英国', 'NL': '荷兰'
            }
            exclude_names = [country_map.get(c, c) for c in exclude_countries if c]
            proxies = [p for p in proxies if p.country not in exclude_names]
        
        if not proxies:
            return Response('# 暂无可用代理\nproxies: []\n', mimetype='text/yaml; charset=utf-8')
        
        # 构建代理列表
        proxy_list = []
        
        # 扩展的国家 emoji 映射表
        country_emoji_map = {
            '中国': '🇨🇳', '香港': '🇭🇰', '台湾': '🇹🇼',
            '美国': '🇺🇸', '加拿大': '🇨🇦',
            '日本': '🇯🇵', '新加坡': '🇸🇬',
            '澳大利亚': '🇦🇺', '俄罗斯': '🇷🇺', '俄罗斯联邦': '🇷🇺',
            '瑞士': '🇨🇭', '德国': '🇩🇪', '法国': '🇫🇷',
            '英国': '🇬🇧', '荷兰': '🇳🇱',
            '韩国': '🇰🇷', '印度': '🇮🇳', '泰国': '🇹🇭',
            '越南': '🇻🇳', '菲律宾': '🇵🇭', '印尼': '🇮🇩', '印度尼西亚': '🇮🇩',
            '马来西亚': '🇲🇾', '巴西': '🇧🇷', '阿根廷': '🇦🇷',
            '墨西哥': '🇲🇽', '智利': '🇨🇱', '哥伦比亚': '🇨🇴',
            '西班牙': '🇪🇸', '意大利': '🇮🇹', '波兰': '🇵🇱',
            '土耳其': '🇹🇷', '以色列': '🇮🇱', '阿联酋': '🇦🇪',
            '南非': '🇿🇦', '埃及': '🇪🇬', '尼日利亚': '🇳🇬',
            '乌克兰': '🇺🇦', '罗马尼亚': '🇷🇴', '捷克': '🇨🇿',
            '希腊': '🇬🇷', '葡萄牙': '🇵🇹', '瑞典': '🇸🇪',
            '挪威': '🇳🇴', '丹麦': '🇩🇰', '芬兰': '🇫🇮',
            '奥地利': '🇦🇹', '比利时': '🇧🇪', '爱尔兰': '🇮🇪',
            '阿尔巴尼亚': '🇦🇱', '保加利亚': '🇧🇬', '塞尔维亚': '🇷🇸',
            '克罗地亚': '🇭🇷', '匈牙利': '🇭🇺', '斯洛伐克': '🇸🇰',
            '斯洛文尼亚': '🇸🇮', '立陶宛': '🇱🇹', '拉脱维亚': '🇱🇻',
            '爱沙尼亚': '🇪🇪', '乌拉圭': '🇺🇾', '巴拉圭': '🇵🇾',
            '新西兰': '🇳🇿', '巴基斯坦': '🇵🇰', '孟加拉国': '🇧🇩'
        }
        
        for p in proxies:
            # 生成代理名称
            if p.country and p.country.strip() and p.country.strip() != '未知':
                # 有国家信息：显示国旗+国家+IP
                country_name = p.country.strip()
                country_emoji = country_emoji_map.get(country_name, '🌍')
                proxy_name = f'{country_emoji} {country_name}_{p.ip}'
            else:
                # 没有国家信息：只显示IP+端口
                proxy_name = f'{p.ip}_{p.port}'
            
            if p.protocol in ['http', 'https']:
                proxy_node = {
                    'name': proxy_name,
                    'type': 'http',
                    'server': p.ip,
                    'port': p.port
                }
                if p.username and p.password:
                    proxy_node['username'] = p.username
                    proxy_node['password'] = p.password
                    
            elif p.protocol == 'socks5':
                proxy_node = {
                    'name': proxy_name,
                    'type': 'socks5',
                    'server': p.ip,
                    'port': p.port
                }
                if p.username and p.password:
                    proxy_node['username'] = p.username
                    proxy_node['password'] = p.password
            else:
                continue
            
            proxy_list.append(proxy_node)
        
        if not proxy_list:
            return Response('# 暂无支持的代理类型（需要 http/https/socks5）\nproxies: []\n', 
                          mimetype='text/yaml; charset=utf-8')
        
        # 转换为 YAML 格式
        yaml_content = yaml.dump({'proxies': proxy_list}, 
                                allow_unicode=True, 
                                default_flow_style=False,
                                sort_keys=False)
        
        # 添加注释头
        header = f"""# ProxyPool Clash 代理列表
# 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# 代理数量: {len(proxy_list)}

"""
        
        return Response(header + yaml_content, mimetype='text/yaml; charset=utf-8')
        
    except Exception as e:
        import traceback
        error_msg = f'# 生成 Clash 代理列表失败: {str(e)}\nproxies: []\n'
        print(f"[clash/proxies] 错误: {e}")
        print(traceback.format_exc())
        return Response(error_msg, mimetype='text/yaml; charset=utf-8', status=500)

############# Clash 订阅接口 end ################

############# V2Ray 订阅接口 ################

# V2Ray 订阅接口
@app.route('/v2ray', methods=['GET'])
@api_enabled_required
def v2ray_subscribe():
    """
    返回 V2Ray 订阅配置（VMess 格式）
    支持参数：
    - username: 用户名（必填）
    - password: 密码（必填）
    - c: 按国家筛选，多个国家用逗号分隔 (如: c=CN,US)
    - nc: 排除指定国家 (如: nc=CN)
    - protocol: 筛选协议类型（http/https/socks5）
    - limit: 限制代理数量，默认返回全部
    """
    try:
        # URL 参数认证
        username = request.args.get('username')
        password = request.args.get('password')
        
        if not username or not password:
            return jsonify({
                'success': False,
                'message': 'V2Ray 订阅需要认证，请提供 username 和 password 参数'
            }), 401
        
        # 验证账号密码
        user = auth_manager.authenticate(username, password)
        if not user:
            return jsonify({
                'success': False,
                'message': '用户名或密码错误'
            }), 401
        
        print(f"[v2ray] 用户 {username} 认证成功")
        
        # 获取查询参数
        countries = request.args.get('c', '').upper().split(',') if request.args.get('c') else None
        exclude_countries = request.args.get('nc', '').upper().split(',') if request.args.get('nc') else None
        protocol = request.args.get('protocol', None)
        limit = request.args.get('limit', -1, type=int)
        
        print(f"[v2ray] 请求参数: countries={countries}, exclude={exclude_countries}, protocol={protocol}, limit={limit}")
        
        # 从数据库获取代理
        if protocol:
            proxies = conn.get_by_protocol(protocol, limit)
        else:
            proxies = conn.getValidatedRandom(limit)
        
        # 按国家筛选
        if countries and countries != ['']:
            country_map = {
                'CN': '中国', 'HK': '香港', 'TW': '台湾',
                'US': '美国', 'CA': '加拿大',
                'JP': '日本', 'SG': '新加坡',
                'AU': '澳大利亚', 'RU': '俄罗斯',
                'CH': '瑞士', 'DE': '德国', 'FR': '法国',
                'GB': '英国', 'NL': '荷兰'
            }
            country_names = [country_map.get(c, c) for c in countries if c]
            proxies = [p for p in proxies if p.country in country_names]
            print(f"[v2ray] 国家筛选后: {len(proxies)} 个代理")
        
        # 排除指定国家
        if exclude_countries and exclude_countries != ['']:
            country_map = {
                'CN': '中国', 'HK': '香港', 'TW': '台湾',
                'US': '美国', 'CA': '加拿大',
                'JP': '日本', 'SG': '新加坡',
                'AU': '澳大利亚', 'RU': '俄罗斯',
                'CH': '瑞士', 'DE': '德国', 'FR': '法国',
                'GB': '英国', 'NL': '荷兰'
            }
            exclude_names = [country_map.get(c, c) for c in exclude_countries if c]
            proxies = [p for p in proxies if p.country not in exclude_names]
            print(f"[v2ray] 排除国家后: {len(proxies)} 个代理")
        
        if not proxies:
            return Response('# 暂无可用代理\n', mimetype='text/plain; charset=utf-8')
        
        # 检查是否有支持的代理
        supported_proxies = [p for p in proxies if p.protocol in ['http', 'https', 'socks4', 'socks5']]
        if not supported_proxies:
            return Response('# 暂无支持的代理类型（需要 http/https/socks4/socks5）\n', mimetype='text/plain; charset=utf-8')
        
        # 根据代理类型生成不同的链接格式
        import base64
        import json
        import uuid
        
        proxy_links = []
        for i, p in enumerate(proxies):
            if p.protocol in ['http', 'https', 'socks4', 'socks5']:
                country = p.country or '未知'
                remark = f'{country}_{p.ip}'
                remark_encoded = remark  # 直接使用备注，不进行编码
                
                if p.protocol in ['http', 'https']:
                    # HTTP/HTTPS 代理生成 VMess 格式
                    vmess_uuid = str(uuid.uuid4())
                    
                    vmess_data = {
                        'v': '2',
                        'ps': remark,
                        'add': p.ip,
                        'port': str(p.port),
                        'id': vmess_uuid,
                        'aid': '0',
                        'net': 'tcp',
                        'type': 'none',
                        'host': '',
                        'path': '',
                        'tls': 'none'
                    }
                    
                    if p.username and p.password:
                        vmess_data['net'] = 'http'
                        vmess_data['type'] = 'http'
                        vmess_data['host'] = f"{p.username}:{p.password}@{p.ip}:{p.port}"
                    
                    vmess_json = json.dumps(vmess_data)
                    vmess_base64 = base64.b64encode(vmess_json.encode('utf-8')).decode('utf-8')
                    proxy_link = f"vmess://{vmess_base64}"
                    
                elif p.protocol in ['socks4', 'socks5']:
                    # SOCKS 代理生成 socks:// 格式
                    if p.username and p.password:
                        auth_info = f"{p.username}:{p.password}"
                        auth_base64 = base64.b64encode(auth_info.encode('utf-8')).decode('utf-8')
                        proxy_link = f"socks://{auth_base64}@{p.ip}:{p.port}#{remark_encoded}"
                    else:
                        proxy_link = f"socks://{p.ip}:{p.port}#{remark_encoded}"
                
                proxy_links.append(proxy_link)
        
        # 将所有代理链接聚合后用 Base64 编码
        all_links = '\n'.join(proxy_links)
        result_base64 = base64.b64encode(all_links.encode('utf-8')).decode('utf-8')
        result = result_base64
        
        print(f"[v2ray] 成功生成配置，包含 {len(proxy_links)} 个代理")
        print(f"[v2ray] 处理的代理类型: {[p.protocol for p in proxies]}")
        print(f"[v2ray] 支持的代理数量: {len([p for p in proxies if p.protocol in ['http', 'https', 'socks4', 'socks5']])}")
        print(f"[v2ray] Base64编码结果长度: {len(result)}")
        
        # 直接返回 Base64 编码的结果，不添加注释头
        return Response(result, mimetype='text/plain; charset=utf-8')
        
    except Exception as e:
        import traceback
        error_msg = f'# 生成 V2Ray 配置失败: {str(e)}\n'
        print(f"[v2ray] 错误: {e}")
        print(traceback.format_exc())
        return Response(error_msg, mimetype='text/plain; charset=utf-8', status=500)

############# V2Ray 订阅接口 end ################

############# 订阅链接生成接口 ################

# 生成订阅链接接口
@app.route('/generate_subscription_links', methods=['POST'])
@token_required
def generate_subscription_links():
    """
    生成加密的订阅链接
    请求体: {
        "type": "clash|v2ray|both",
        "permanent": false,  // 可选：是否生成永久链接，默认false
        "params": {
            "c": "CN,US",  // 可选：按国家筛选
            "nc": "CN",    // 可选：排除国家
            "protocol": "http",  // 可选：协议筛选
            "limit": 100   // 可选：限制数量
        }
    }
    返回: {
        "success": true,
        "links": {
            "clash": "http://localhost:5000/subscribe/clash?token=...",
            "v2ray": "http://localhost:5000/subscribe/v2ray?token=..."
        },
        "permanent": false,
        "expires_in": 3600  // 永久链接时为null
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'message': '请提供请求数据'
            }), 400
        
        sub_type = data.get('type', 'both')
        permanent = data.get('permanent', False)
        params = data.get('params', {})
        
        if sub_type not in ['clash', 'v2ray', 'both']:
            return jsonify({
                'success': False,
                'message': 'type 参数必须是 clash、v2ray 或 both'
            }), 400
        
        # 生成加密token
        import base64
        import json
        import time
        import hashlib
        
        # 创建订阅token payload
        if permanent:
            # 永久链接：使用用户名和参数的哈希作为token的一部分
            params_str = json.dumps(params, sort_keys=True)
            token_data = f"{request.user['username']}:{params_str}"
            token_hash = hashlib.sha256(token_data.encode()).hexdigest()[:16]
            
            # 创建永久token payload（不过期）
            token_payload = {
                'username': request.user['username'],
                'role': request.user['role'],
                'params': params,
                'permanent': True,
                'token_hash': token_hash,
                'iat': int(time.time())
            }
            
            # 生成永久token（不设置过期时间）
            subscription_token = jwt.encode(token_payload, auth_manager.secret_key, algorithm='HS256')
        else:
            # 临时链接：1小时过期
            token_payload = {
                'username': request.user['username'],
                'role': request.user['role'],
                'params': params,
                'permanent': False,
                'exp': int(time.time()) + 3600,  # 1小时过期
                'iat': int(time.time())
            }
            
            subscription_token = jwt.encode(token_payload, auth_manager.secret_key, algorithm='HS256')
        
        # 将参数编码到token中
        params_encoded = base64.b64encode(json.dumps(params).encode()).decode()
        
        # 对token进行URL编码
        import urllib.parse
        token_encoded = urllib.parse.quote(subscription_token, safe='')
        params_encoded_url = urllib.parse.quote(params_encoded, safe='')
        
        # 构建订阅链接
        base_url = request.host_url.rstrip('/')
        links = {}
        
        if sub_type in ['clash', 'both']:
            links['clash'] = f"{base_url}/subscribe/clash?token={token_encoded}&params={params_encoded_url}"
        
        if sub_type in ['v2ray', 'both']:
            links['v2ray'] = f"{base_url}/subscribe/v2ray?token={token_encoded}&params={params_encoded_url}"
        
        # 保存订阅链接到 sub.json 文件
        save_subscription_to_file(request.user['username'], links, permanent, params)
        
        result = {
            'success': True,
            'links': links,
            'permanent': permanent,
            'expires_in': None if permanent else 3600,
            'message': '永久订阅链接生成成功' if permanent else '订阅链接生成成功，请在1小时内使用'
        }
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'生成订阅链接失败: {str(e)}'
        }), 500

# 加密的Clash订阅接口
@app.route('/subscribe/clash', methods=['GET'])
def subscribe_clash():
    """
    加密的Clash订阅接口
    参数: token (必填) - 订阅token
    参数: params (可选) - 编码的参数
    """
    try:
        # 获取token并进行URL解码
        import urllib.parse
        token = request.args.get('token')
        if not token:
            return jsonify({
                'success': False,
                'message': '缺少订阅token'
            }), 401
        
        # URL解码token
        token = urllib.parse.unquote(token)
        
        # 验证token
        try:
            payload = jwt.decode(token, auth_manager.secret_key, algorithms=['HS256'])
            
            # 检查是否为永久链接
            if payload.get('permanent', False):
                # 永久链接：验证用户是否存在且有效
                username = payload.get('username')
                if not username:
                    return jsonify({
                        'success': False,
                        'message': '订阅token无效'
                    }), 401
                
                # 验证用户是否仍然存在
                users = auth_manager._load_users()
                if username not in users:
                    return jsonify({
                        'success': False,
                        'message': '用户不存在，订阅链接已失效'
                    }), 401
            else:
                # 临时链接：使用原有的验证逻辑
                payload = auth_manager.verify_token(token)
                if not payload:
                    return jsonify({
                        'success': False,
                        'message': '订阅token无效或已过期'
                    }), 401
        except jwt.ExpiredSignatureError:
            return jsonify({
                'success': False,
                'message': '订阅token已过期'
            }), 401
        except jwt.InvalidTokenError:
            return jsonify({
                'success': False,
                'message': '订阅token无效'
            }), 401
        
        # 解析参数
        params = {}
        params_encoded = request.args.get('params')
        if params_encoded:
            try:
                import base64
                import json
                params = json.loads(base64.b64decode(params_encoded).decode())
            except Exception as e:
                print(f"[subscribe/clash] 参数解析失败: {e}")
        
        # 获取查询参数
        countries = params.get('c', '').upper().split(',') if params.get('c') else None
        exclude_countries = params.get('nc', '').upper().split(',') if params.get('nc') else None
        protocol = params.get('protocol', None)
        limit = params.get('limit', -1)
        if limit != -1:
            limit = int(limit)
        
        print(f"[subscribe/clash] 用户 {payload['username']} 请求Clash订阅，参数: {params}")
        
        # 从数据库获取代理
        if protocol:
            proxies = conn.get_by_protocol(protocol, limit)
        else:
            proxies = conn.getValidatedRandom(limit)
        
        # 按国家筛选
        if countries and countries != ['']:
            country_map = {
                'CN': '中国', 'HK': '香港', 'TW': '台湾',
                'US': '美国', 'CA': '加拿大',
                'JP': '日本', 'SG': '新加坡',
                'AU': '澳大利亚', 'RU': '俄罗斯',
                'CH': '瑞士', 'DE': '德国', 'FR': '法国',
                'GB': '英国', 'NL': '荷兰'
            }
            country_names = [country_map.get(c, c) for c in countries if c]
            proxies = [p for p in proxies if p.country in country_names]
        
        # 排除指定国家
        if exclude_countries and exclude_countries != ['']:
            country_map = {
                'CN': '中国', 'HK': '香港', 'TW': '台湾',
                'US': '美国', 'CA': '加拿大',
                'JP': '日本', 'SG': '新加坡',
                'AU': '澳大利亚', 'RU': '俄罗斯',
                'CH': '瑞士', 'DE': '德国', 'FR': '法国',
                'GB': '英国', 'NL': '荷兰'
            }
            exclude_names = [country_map.get(c, c) for c in exclude_countries if c]
            proxies = [p for p in proxies if p.country not in exclude_names]
        
        if not proxies:
            return Response('# 暂无可用代理\nproxies: []\n', mimetype='text/yaml; charset=utf-8')
        
        # 构建完整的 Clash 配置
        clash_config = {
            'port': 7890,
            'socks-port': 7891,
            'allow-lan': False,
            'mode': 'rule',
            'log-level': 'info',
            'external-controller': '127.0.0.1:9090',
            'proxies': []
        }
        
        # 将代理转换为 Clash 格式
        proxy_names = []
        
        # 扩展的国家 emoji 映射表
        country_emoji_map = {
            '中国': '🇨🇳', '香港': '🇭🇰', '台湾': '🇹🇼',
            '美国': '🇺🇸', '加拿大': '🇨🇦',
            '日本': '🇯🇵', '新加坡': '🇸🇬',
            '澳大利亚': '🇦🇺', '俄罗斯': '🇷🇺', '俄罗斯联邦': '🇷🇺',
            '瑞士': '🇨🇭', '德国': '🇩🇪', '法国': '🇫🇷',
            '英国': '🇬🇧', '荷兰': '🇳🇱',
            '韩国': '🇰🇷', '印度': '🇮🇳', '泰国': '🇹🇭',
            '越南': '🇻🇳', '菲律宾': '🇵🇭', '印尼': '🇮🇩', '印度尼西亚': '🇮🇩',
            '马来西亚': '🇲🇾', '巴西': '🇧🇷', '阿根廷': '🇦🇷',
            '墨西哥': '🇲🇽', '智利': '🇨🇱', '哥伦比亚': '🇨🇴',
            '西班牙': '🇪🇸', '意大利': '🇮🇹', '波兰': '🇵🇱',
            '土耳其': '🇹🇷', '以色列': '🇮🇱', '阿联酋': '🇦🇪',
            '南非': '🇿🇦', '埃及': '🇪🇬', '尼日利亚': '🇳🇬',
            '乌克兰': '🇺🇦', '罗马尼亚': '🇷🇴', '捷克': '🇨🇿',
            '希腊': '🇬🇷', '葡萄牙': '🇵🇹', '瑞典': '🇸🇪',
            '挪威': '🇳🇴', '丹麦': '🇩🇰', '芬兰': '🇫🇮',
            '奥地利': '🇦🇹', '比利时': '🇧🇪', '爱尔兰': '🇮🇪',
            '阿尔巴尼亚': '🇦🇱', '保加利亚': '🇧🇬', '塞尔维亚': '🇷🇸',
            '克罗地亚': '🇭🇷', '匈牙利': '🇭🇺', '斯洛伐克': '🇸🇰',
            '斯洛文尼亚': '🇸🇮', '立陶宛': '🇱🇹', '拉脱维亚': '🇱🇻',
            '爱沙尼亚': '🇪🇪', '乌拉圭': '🇺🇾', '巴拉圭': '🇵🇾',
            '新西兰': '🇳🇿', '巴基斯坦': '🇵🇰', '孟加拉国': '🇧🇩'
        }
        
        for p in proxies:
            # 生成代理名称
            if p.country and p.country.strip() and p.country.strip() != '未知':
                # 有国家信息：显示国旗+国家+IP
                country_name = p.country.strip()
                country_emoji = country_emoji_map.get(country_name, '🌍')
                proxy_name = f'{country_emoji} {country_name}_{p.ip}'
            else:
                # 没有国家信息：只显示IP+端口
                proxy_name = f'{p.ip}_{p.port}'
            
            if p.protocol in ['http', 'https']:
                proxy_node = {
                    'name': proxy_name,
                    'type': 'http',
                    'server': p.ip,
                    'port': p.port
                }
                if p.username and p.password:
                    proxy_node['username'] = p.username
                    proxy_node['password'] = p.password
                    
            elif p.protocol == 'socks5':
                proxy_node = {
                    'name': proxy_name,
                    'type': 'socks5',
                    'server': p.ip,
                    'port': p.port
                }
                if p.username and p.password:
                    proxy_node['username'] = p.username
                    proxy_node['password'] = p.password
            else:
                continue
            
            clash_config['proxies'].append(proxy_node)
            proxy_names.append(proxy_name)
        
        if not clash_config['proxies']:
            return Response('# 暂无支持的代理类型（需要 http/https/socks5）\nproxies: []\n', 
                          mimetype='text/yaml; charset=utf-8')
        
        # 添加代理组
        clash_config['proxy-groups'] = [
            {
                'name': '全局选择',
                'type': 'select',
                'proxies': ['延迟最低', '负载均衡', '失败切换'] + proxy_names[:50]  # 只显示前50个以避免太长
            },
            {
                'name': '延迟最低',
                'type': 'url-test',
                'proxies': proxy_names,
                'url': 'http://www.gstatic.com/generate_204',
                'interval': 300
            },
            {
                'name': '负载均衡',
                'type': 'load-balance',
                'proxies': proxy_names,
                'url': 'http://www.gstatic.com/generate_204',
                'interval': 300
            },
            {
                'name': '失败切换',
                'type': 'fallback',
                'proxies': proxy_names,
                'url': 'http://www.gstatic.com/generate_204',
                'interval': 300
            }
        ]
        
        # 添加基本规则
        clash_config['rules'] = [
            'DOMAIN-SUFFIX,local,DIRECT',
            'IP-CIDR,127.0.0.0/8,DIRECT',
            'IP-CIDR,192.168.0.0/16,DIRECT',
            'IP-CIDR,10.0.0.0/8,DIRECT',
            'IP-CIDR,172.16.0.0/12,DIRECT',
            'GEOIP,CN,DIRECT',
            'MATCH,全局选择'
        ]
        
        # 转换为 YAML 格式
        yaml_content = yaml.dump(clash_config, 
                                allow_unicode=True, 
                                default_flow_style=False,
                                sort_keys=False)
        
        # 添加注释头
        header = f"""# ProxyPool Clash 订阅配置
# 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# 代理数量: {len(clash_config['proxies'])}
# 用户: {payload['username']}
# 项目地址: https://github.com/huppugo1/ProxyPoolWithUI

"""
        
        return Response(header + yaml_content, mimetype='text/yaml; charset=utf-8')
        
    except Exception as e:
        import traceback
        error_msg = f'# 生成 Clash 配置失败: {str(e)}\n'
        print(f"[subscribe/clash] 错误: {e}")
        print(traceback.format_exc())
        return Response(error_msg, mimetype='text/yaml; charset=utf-8', status=500)

# 加密的V2Ray订阅接口
@app.route('/subscribe/v2ray', methods=['GET'])
def subscribe_v2ray():
    """
    加密的V2Ray订阅接口
    参数: token (必填) - 订阅token
    参数: params (可选) - 编码的参数
    """
    try:
        # 获取token并进行URL解码
        import urllib.parse
        token = request.args.get('token')
        if not token:
            return jsonify({
                'success': False,
                'message': '缺少订阅token'
            }), 401
        
        # URL解码token
        token = urllib.parse.unquote(token)
        
        # 验证token
        try:
            payload = jwt.decode(token, auth_manager.secret_key, algorithms=['HS256'])
            
            # 检查是否为永久链接
            if payload.get('permanent', False):
                # 永久链接：验证用户是否存在且有效
                username = payload.get('username')
                if not username:
                    return jsonify({
                        'success': False,
                        'message': '订阅token无效'
                    }), 401
                
                # 验证用户是否仍然存在
                users = auth_manager._load_users()
                if username not in users:
                    return jsonify({
                        'success': False,
                        'message': '用户不存在，订阅链接已失效'
                    }), 401
            else:
                # 临时链接：使用原有的验证逻辑
                payload = auth_manager.verify_token(token)
                if not payload:
                    return jsonify({
                        'success': False,
                        'message': '订阅token无效或已过期'
                    }), 401
        except jwt.ExpiredSignatureError:
            return jsonify({
                'success': False,
                'message': '订阅token已过期'
            }), 401
        except jwt.InvalidTokenError:
            return jsonify({
                'success': False,
                'message': '订阅token无效'
            }), 401
        
        # 解析参数
        params = {}
        params_encoded = request.args.get('params')
        if params_encoded:
            try:
                import base64
                import json
                params = json.loads(base64.b64decode(params_encoded).decode())
            except Exception as e:
                print(f"[subscribe/v2ray] 参数解析失败: {e}")
        
        # 获取查询参数
        countries = params.get('c', '').upper().split(',') if params.get('c') else None
        exclude_countries = params.get('nc', '').upper().split(',') if params.get('nc') else None
        protocol = params.get('protocol', None)
        limit = params.get('limit', -1)
        if limit != -1:
            limit = int(limit)
        
        print(f"[subscribe/v2ray] 用户 {payload['username']} 请求V2Ray订阅，参数: {params}")
        
        # 从数据库获取代理
        if protocol:
            proxies = conn.get_by_protocol(protocol, limit)
        else:
            proxies = conn.getValidatedRandom(limit)
        
        # 按国家筛选
        if countries and countries != ['']:
            country_map = {
                'CN': '中国', 'HK': '香港', 'TW': '台湾',
                'US': '美国', 'CA': '加拿大',
                'JP': '日本', 'SG': '新加坡',
                'AU': '澳大利亚', 'RU': '俄罗斯',
                'CH': '瑞士', 'DE': '德国', 'FR': '法国',
                'GB': '英国', 'NL': '荷兰'
            }
            country_names = [country_map.get(c, c) for c in countries if c]
            proxies = [p for p in proxies if p.country in country_names]
        
        # 排除指定国家
        if exclude_countries and exclude_countries != ['']:
            country_map = {
                'CN': '中国', 'HK': '香港', 'TW': '台湾',
                'US': '美国', 'CA': '加拿大',
                'JP': '日本', 'SG': '新加坡',
                'AU': '澳大利亚', 'RU': '俄罗斯',
                'CH': '瑞士', 'DE': '德国', 'FR': '法国',
                'GB': '英国', 'NL': '荷兰'
            }
            exclude_names = [country_map.get(c, c) for c in exclude_countries if c]
            proxies = [p for p in proxies if p.country not in exclude_names]
        
        if not proxies:
            return Response('# 暂无可用代理\n', mimetype='text/plain; charset=utf-8')
        
        # 检查是否有支持的代理
        supported_proxies = [p for p in proxies if p.protocol in ['http', 'https', 'socks4', 'socks5']]
        if not supported_proxies:
            return Response('# 暂无支持的代理类型（需要 http/https/socks4/socks5）\n', mimetype='text/plain; charset=utf-8')
        
        # 根据代理类型生成不同的链接格式
        import base64
        import json
        import uuid
        
        proxy_links = []
        for i, p in enumerate(proxies):
            if p.protocol in ['http', 'https', 'socks4', 'socks5']:
                country = p.country or '未知'
                remark = f'{country}_{p.ip}'
                remark_encoded = remark  # 直接使用备注，不进行编码
                
                if p.protocol in ['http', 'https']:
                    # HTTP/HTTPS 代理生成 VMess 格式
                    vmess_uuid = str(uuid.uuid4())
                    
                    vmess_data = {
                        'v': '2',
                        'ps': remark,
                        'add': p.ip,
                        'port': str(p.port),
                        'id': vmess_uuid,
                        'aid': '0',
                        'net': 'tcp',
                        'type': 'none',
                        'host': '',
                        'path': '',
                        'tls': 'none'
                    }
                    
                    if p.username and p.password:
                        vmess_data['net'] = 'http'
                        vmess_data['type'] = 'http'
                        vmess_data['host'] = f"{p.username}:{p.password}@{p.ip}:{p.port}"
                    
                    vmess_json = json.dumps(vmess_data)
                    vmess_base64 = base64.b64encode(vmess_json.encode('utf-8')).decode('utf-8')
                    proxy_link = f"vmess://{vmess_base64}"
                    
                elif p.protocol in ['socks4', 'socks5']:
                    # SOCKS 代理生成 socks:// 格式
                    if p.username and p.password:
                        auth_info = f"{p.username}:{p.password}"
                        auth_base64 = base64.b64encode(auth_info.encode('utf-8')).decode('utf-8')
                        proxy_link = f"socks://{auth_base64}@{p.ip}:{p.port}#{remark_encoded}"
                    else:
                        proxy_link = f"socks://{p.ip}:{p.port}#{remark_encoded}"
                
                proxy_links.append(proxy_link)
        
        # 将所有代理链接聚合后用 Base64 编码
        all_links = '\n'.join(proxy_links)
        result_base64 = base64.b64encode(all_links.encode('utf-8')).decode('utf-8')
        result = result_base64
        
        print(f"[subscribe/v2ray] 成功生成配置，包含 {len(proxy_links)} 个代理")
        
        # 直接返回 Base64 编码的结果，不添加注释头
        return Response(result, mimetype='text/plain; charset=utf-8')
        
    except Exception as e:
        import traceback
        error_msg = f'# 生成 V2Ray 配置失败: {str(e)}\n'
        print(f"[subscribe/v2ray] 错误: {e}")
        print(traceback.format_exc())
        return Response(error_msg, mimetype='text/plain; charset=utf-8', status=500)

############# 订阅链接管理接口 ################

def save_subscription_to_file(username, links, permanent, params):
    """
    保存订阅链接到 sub.json 文件
    """
    try:
        import json
        import time
        
        sub_file = SUBSCRIPTIONS_FILE
        
        # 读取现有数据
        if os.path.exists(sub_file):
            with open(sub_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {'subscriptions': []}
        
        # 添加新的订阅链接
        current_time = time.time()
        for link_type, url in links.items():
            subscription = {
                'id': f"sub_{int(current_time * 1000)}_{link_type}",
                'username': username,
                'type': link_type,
                'url': url,
                'created_at': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time)),
                'permanent': permanent,
                'expires_at': None if permanent else time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time + 3600)),
                'params': params
            }
            data['subscriptions'].append(subscription)
        
        # 保存到文件
        with open(sub_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
    except Exception as e:
        pass  # 静默处理保存错误

# 获取已生成的订阅链接列表
@app.route('/subscription_links', methods=['GET'])
@token_required
def get_subscription_links():
    """
    获取当前用户已生成的订阅链接列表
    返回: {"success": true, "links": [...]}
    """
    try:
        username = request.user['username']
        
        # 从 sub.json 文件读取订阅链接
        sub_file = SUBSCRIPTIONS_FILE
        
        if os.path.exists(sub_file):
            with open(sub_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 过滤当前用户的订阅链接
                user_links = [link for link in data.get('subscriptions', []) if link.get('username') == username]
        else:
            user_links = []
        
        return jsonify({
            'success': True,
            'links': user_links
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'获取订阅链接失败: {str(e)}'
        }), 500

# 删除订阅链接
@app.route('/subscription_links/<link_id>', methods=['DELETE'])
@token_required
def delete_subscription_link(link_id):
    """
    删除指定的订阅链接
    参数: link_id - 订阅链接ID
    """
    try:
        username = request.user['username']
        
        # 从 sub.json 文件读取并删除订阅链接
        sub_file = SUBSCRIPTIONS_FILE
        
        if os.path.exists(sub_file):
            with open(sub_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {'subscriptions': []}
        
        # 过滤掉要删除的链接
        original_count = len(data['subscriptions'])
        data['subscriptions'] = [
            link for link in data['subscriptions'] 
            if not (link.get('id') == link_id and link.get('username') == username)
        ]
        
        # 保存回文件
        with open(sub_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        deleted_count = original_count - len(data['subscriptions'])
        
        return jsonify({
            'success': True,
            'message': f'订阅链接删除成功，共删除 {deleted_count} 个链接'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'删除订阅链接失败: {str(e)}'
        }), 500

# 刷新订阅链接（重新生成）
@app.route('/subscription_links/<link_id>/refresh', methods=['POST'])
@token_required
def refresh_subscription_link(link_id):
    """
    刷新指定的订阅链接（重新生成token）
    参数: link_id - 订阅链接ID
    """
    try:
        username = request.user['username']
        
        # 从 sub.json 文件读取订阅链接
        sub_file = SUBSCRIPTIONS_FILE
        
        if not os.path.exists(sub_file):
            return jsonify({
                'success': False,
                'message': '订阅文件不存在'
            }), 404
        
        with open(sub_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 找到要刷新的链接
        target_link = None
        for link in data['subscriptions']:
            if link.get('id') == link_id and link.get('username') == username:
                target_link = link
                break
        
        if not target_link:
            return jsonify({
                'success': False,
                'message': '订阅链接不存在'
            }), 404
        
        # 重新生成token
        params = target_link.get('params', {})
        permanent = target_link.get('permanent', False)
        
        # 生成新的JWT token
        if permanent:
            # 永久链接：不设置过期时间，使用token_hash
            token_hash = hashlib.md5(f"{username}_{json.dumps(params, sort_keys=True)}".encode()).hexdigest()
            token_payload = {
                'username': username,
                'role': 'admin',
                'params': params,
                'permanent': True,
                'token_hash': token_hash
            }
        else:
            # 临时链接：设置1小时过期时间
            token_payload = {
                'username': username,
                'role': 'admin',
                'params': params,
                'permanent': False,
                'exp': int(time.time()) + 3600  # 1小时后过期
            }
        
        # 生成新的token
        new_token = jwt.encode(token_payload, auth_manager.secret_key, algorithm='HS256')
        token_encoded = urllib.parse.quote(new_token, safe='')
        params_encoded = base64.b64encode(json.dumps(params).encode()).decode()
        
        # 生成新的URL
        subscription_type = target_link.get('type', 'clash')
        new_url = f"http://localhost:5000/subscribe/{subscription_type}?token={token_encoded}&params={params_encoded}"
        
        # 更新链接的URL和创建时间
        target_link['url'] = new_url
        target_link['created_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        if not permanent:
            target_link['expires_at'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(token_payload['exp']))
        
        # 保存回文件
        with open(sub_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return jsonify({
            'success': True,
            'message': '订阅链接刷新成功',
            'new_url': new_url
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'刷新订阅链接失败: {str(e)}'
        }), 500

############# 订阅链接管理接口 end ################

############# API接口管理 ################

# API接口状态配置文件路径
# API状态文件路径已在 config/__init__.py 中定义

# 默认API接口状态配置
DEFAULT_API_ENABLED_STATUS = {
    'auth': {
        '/auth/login': True,
        '/auth/verify': True,
        '/auth/change_password': True
    },
    'proxy': {
        '/fetch_random': True,
        '/fetch_all': True,
        '/fetch_http': True,
        '/fetch_https': True,
        '/fetch_socks4': True,
        '/fetch_socks5': True
    },
    'clash': {
        '/clash': True,
        '/clash/proxies': True
    },
    'v2ray': {
        '/v2ray': True
    },
    'subscription': {
        '/generate_subscription_links': True,
        '/subscribe/clash': True,
        '/subscribe/v2ray': True,
        '/subscription_links': True
    },
    'management': {
        '/proxies_status': True,
        '/fetchers_status': True,
        '/add_proxy': True,
        '/delete_proxy': True,
        '/fetcher_enable': True,
        '/ping': True
    }
}

# 加载API状态配置
def load_api_status():
    """从文件加载API状态配置"""
    try:
        if os.path.exists(API_STATUS_FILE):
            with open(API_STATUS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            # 如果文件不存在，创建默认配置
            save_api_status(DEFAULT_API_ENABLED_STATUS)
            return DEFAULT_API_ENABLED_STATUS
    except Exception as e:
        print(f"[API管理] 加载API状态配置失败: {e}")
        return DEFAULT_API_ENABLED_STATUS

# 保存API状态配置
def save_api_status(status):
    """保存API状态配置到文件"""
    try:
        with open(API_STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[API管理] 保存API状态配置失败: {e}")

# 初始化API状态配置
API_ENABLED_STATUS = load_api_status()

def check_api_enabled(api_path: str) -> bool:
    """检查API接口是否启用"""
    for category, apis in API_ENABLED_STATUS.items():
        if api_path in apis:
            return apis[api_path]
    return True  # 默认启用

def disable_api(api_path: str) -> bool:
    """禁用API接口"""
    for category, apis in API_ENABLED_STATUS.items():
        if api_path in apis:
            apis[api_path] = False
            save_api_status(API_ENABLED_STATUS)  # 保存到文件
            return True
    return False

def enable_api(api_path: str) -> bool:
    """启用API接口"""
    for category, apis in API_ENABLED_STATUS.items():
        if api_path in apis:
            apis[api_path] = True
            save_api_status(API_ENABLED_STATUS)  # 保存到文件
            return True
    return False

# 获取API状态列表
@app.route('/api_status', methods=['GET'])
@token_required
def get_api_status():
    """
    获取所有API接口的启用状态
    返回: {"success": true, "apis": [...]}
    """
    try:
        apis = []
        for category, api_list in API_ENABLED_STATUS.items():
            for api_path, enabled in api_list.items():
                apis.append({
                    'path': api_path,
                    'category': category,
                    'enabled': enabled
                })
        
        return jsonify({
            'success': True,
            'apis': apis
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'获取API状态失败: {str(e)}'
        }), 500

# 切换API状态
@app.route('/api_toggle/<path:api_path>', methods=['POST'])
@token_required
def toggle_api_status(api_path):
    """
    切换API接口的启用/禁用状态
    参数: api_path - API路径
    """
    try:
        # 确保路径以/开头
        if not api_path.startswith('/'):
            api_path = '/' + api_path
        
        # 检查当前状态
        current_status = check_api_enabled(api_path)
        
        if current_status:
            # 当前启用，则禁用
            success = disable_api(api_path)
            action = 'disabled'
        else:
            # 当前禁用，则启用
            success = enable_api(api_path)
            action = 'enabled'
        
        if success:
            return jsonify({
                'success': True,
                'message': f'API {api_path} 已{action}',
                'enabled': not current_status
            })
        else:
            return jsonify({
                'success': False,
                'message': f'API {api_path} 不存在'
            }), 404
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'切换API状态失败: {str(e)}'
        }), 500

############# API接口管理 end ################

############# 以下API主要给网页使用 ################

@app.route('/')
def index():
    return redirect('/web')

# 网页：首页
@app.route('/web', methods=['GET'])
@app.route('/web/', methods=['GET'])
def page_index():
    return send_from_directory(STATIC_FOLDER, 'index.html')

# 网页：爬取器状态
@app.route('/web/fetchers', methods=['GET'])
@app.route('/web/fetchers/', methods=['GET'])
def page_fetchers():
    return send_from_directory(STATIC_FOLDER, 'fetchers/index.html')

# 获取代理状态
@app.route('/proxies_status', methods=['GET'])
@token_required
def proxies_status():
    try:
        # 添加超时保护和限制
        import time
        start_time = time.time()
        
        # 限制返回的代理数量，避免数据过大导致超时
        max_proxies = int(request.args.get('limit', 1000))  # 默认最多返回 1000 个
        
        print(f"[proxies_status] 开始查询，限制={max_proxies}")
        
        proxies = conn.getValidatedRandom(max_proxies)
        elapsed1 = time.time() - start_time
        print(f"[proxies_status] 查询代理完成: {len(proxies)} 个 ({elapsed1:.2f}秒)")
        
        proxies = sorted(proxies, key=lambda p: f'{p.protocol}://{p.ip}:{p.port}', reverse=True)
        proxies = [p.to_dict() for p in proxies]
        
        elapsed2 = time.time() - start_time
        print(f"[proxies_status] 数据转换完成 ({elapsed2:.2f}秒)")

        status = conn.getProxiesStatus()
        
        elapsed3 = time.time() - start_time
        print(f"[proxies_status] 状态统计完成 ({elapsed3:.2f}秒)")
        print(f"[proxies_status] 总耗时: {elapsed3:.2f}秒")

        return jsonify(dict(
            success=True,
            proxies=proxies,
            **status
        ))
    except Exception as e:
        import traceback
        print(f"[proxies_status] 错误: {e}")
        print(traceback.format_exc())
        return jsonify(dict(
            success=False,
            message=f'获取代理状态失败: {str(e)}',
            proxies=[],
            sum_proxies_cnt=0,
            validated_proxies_cnt=0,
            pending_proxies_cnt=0
        )), 500

# 获取爬取器状态
@app.route('/fetchers_status', methods=['GET'])
@token_required
def fetchers_status():
    # 优化：一次性获取所有需要的数据，避免多次锁竞争
    fetchers = conn.getAllFetchers()
    fetchers = [f.to_dict() for f in fetchers]
    
    # 获取所有可用代理用于统计
    proxies = conn.getValidatedRandom(-1)
    
    # 统计每个fetcher的validated_cnt
    validated_cnt_map = {}
    for p in proxies:
        if p.fetcher_name not in validated_cnt_map:
            validated_cnt_map[p.fetcher_name] = 0
        validated_cnt_map[p.fetcher_name] += 1
    
    # 一次性获取所有fetcher的in_db_cnt
    in_db_cnt_map = conn.getProxyCountAll()
    
    for f in fetchers:
        f['validated_cnt'] = validated_cnt_map.get(f['name'], 0)
        f['in_db_cnt'] = in_db_cnt_map.get(f['name'], 0)
    
    return jsonify(dict(
        success=True,
        fetchers=fetchers
    ))

# 清空爬取器状态
@app.route('/clear_fetchers_status', methods=['GET'])
@token_required
def clear_fetchers_status():
    conn.pushClearFetchersStatus()
    return jsonify(dict(success=True))

# 设置是否启用特定爬取器,?name=str,enable=0/1
@app.route('/fetcher_enable', methods=['GET'])
@token_required
def fetcher_enable():
    name = request.args.get('name')
    enable = request.args.get('enable')
    if enable == '1':
        conn.pushFetcherEnable(name, True)
    else:
        conn.pushFetcherEnable(name, False)
    return jsonify(dict(success=True))

# 手动添加代理
@app.route('/add_proxy', methods=['POST'])
@token_required
def add_proxy():
    try:
        data = request.get_json()
        
        # 验证必填字段
        required_fields = ['fetcher_name', 'protocol', 'ip', 'port']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify(dict(success=False, message=f'缺少必填字段: {field}')), 400
        
        fetcher_name = data['fetcher_name']
        protocol = data['protocol'].lower()
        ip = data['ip'].strip()
        
        # 验证端口
        try:
            port = int(data['port'])
            if port < 1 or port > 65535:
                return jsonify(dict(success=False, message='端口范围必须在 1-65535 之间')), 400
        except ValueError:
            return jsonify(dict(success=False, message='端口必须是数字')), 400
        
        # 验证协议
        valid_protocols = ['http', 'https', 'socks4', 'socks5']
        if protocol not in valid_protocols:
            return jsonify(dict(success=False, message=f'协议必须是以下之一: {", ".join(valid_protocols)}')), 400
        
        # 可选字段
        username = data.get('username', '').strip() or None
        password = data.get('password', '').strip() or None
        country = data.get('country', '').strip() or None
        address = data.get('address', '').strip() or None
        
        print(f"[手动添加代理] {protocol}://{ip}:{port} 来源={fetcher_name}")
        
        # 添加代理到数据库
        conn.pushNewFetch(
            fetcher_name=fetcher_name,
            protocol=protocol,
            ip=ip,
            port=port,
            username=username,
            password=password,
            country=country,
            address=address
        )
        
        print(f"[手动添加代理] 成功添加: {protocol}://{ip}:{port}")
        return jsonify(dict(success=True, message='代理添加成功，等待验证'))
    
    except conn.DBIntegrityError as e:
        error_msg = '该代理已存在（相同协议、IP和端口）'
        print(f"[手动添加代理] 错误: {error_msg}")
        return jsonify(dict(success=False, message=error_msg)), 400
    
    except Exception as e:
        import traceback
        error_msg = str(e)
        print(f"[手动添加代理] 异常: {error_msg}")
        print(traceback.format_exc())
        return jsonify(dict(success=False, message=f'添加失败: {error_msg}')), 500

############# 其他 ################

# 跨域支持，主要是在开发网页端的时候需要使用
def after_request(resp):
    ALLOWED_ORIGIN = ['0.0.0.0', '127.0.0.1', 'localhost']
    origin = request.headers.get('origin', None)
    if origin is not None:
        for item in ALLOWED_ORIGIN:
            if item in origin:
                resp.headers['Access-Control-Allow-Origin'] = origin
                resp.headers['Access-Control-Allow-Credentials'] = 'true'
                resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
                resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
                resp.headers['Access-Control-Max-Age'] = '3600'
    return resp

# 处理 OPTIONS 预检请求
@app.before_request
def handle_preflight():
    if request.method == 'OPTIONS':
        response = app.make_default_options_response()
        ALLOWED_ORIGIN = ['0.0.0.0', '127.0.0.1', 'localhost']
        origin = request.headers.get('origin', None)
        if origin is not None:
            for item in ALLOWED_ORIGIN:
                if item in origin:
                    response.headers['Access-Control-Allow-Origin'] = origin
                    response.headers['Access-Control-Allow-Credentials'] = 'true'
                    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
                    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
                    response.headers['Access-Control-Max-Age'] = '3600'
                    break
        return response

app.after_request(after_request)

def main(proc_lock):
    if proc_lock is not None:
        conn.set_proc_lock(proc_lock)
    
    # 优化Flask配置，启用多线程以提高网络响应性能
    # 数据库连接已经配置为支持多线程访问（check_same_thread=False）
    # 并且使用了WAL模式和适当的锁机制来保证线程安全
    app.run(
        host='0.0.0.0', 
        port=5000, 
        threaded=True,  # 启用多线程，提高并发处理能力
        processes=1,    # 单进程，避免数据库连接冲突
        debug=False,    # 生产环境关闭调试模式
        use_reloader=False  # 关闭自动重载，避免多进程问题
    )

if __name__ == '__main__':
    main(None)
