#!/usr/bin/env python3
# encoding: utf-8

"""
ProxyPool 安全配置脚本
用于生成和配置 JWT 密钥等安全设置
"""

import os
import sys
import secrets
import subprocess
import platform

def generate_jwt_secret_key(length=32):
    """生成安全的JWT密钥"""
    return secrets.token_urlsafe(length)

def print_banner():
    """打印欢迎横幅"""
    print("=" * 80)
    print("🔐 ProxyPool 安全配置工具")
    print("=" * 80)
    print("此工具将帮助您配置 ProxyPool 的安全设置")
    print("=" * 80)

def check_current_config():
    """检查当前配置"""
    print("\n📋 检查当前配置...")
    
    current_key = os.environ.get('JWT_SECRET_KEY')
    if current_key:
        print(f"✅ 已设置 JWT_SECRET_KEY (长度: {len(current_key)})")
        if len(current_key) >= 32:
            print("✅ 密钥长度符合安全要求")
        else:
            print("⚠️  密钥长度不足，建议至少32字符")
    else:
        print("❌ 未设置 JWT_SECRET_KEY 环境变量")

def generate_new_key():
    """生成新的JWT密钥"""
    print("\n🔑 生成新的JWT密钥...")
    
    # 生成32字符的强密钥
    new_key = generate_jwt_secret_key(32)
    print(f"新密钥: {new_key}")
    print(f"密钥长度: {len(new_key)} 字符")
    
    return new_key

def show_setup_commands(key):
    """显示配置信息"""
    print("\n📝 配置信息:")
    print("-" * 50)
    print("✅ 密钥已生成并保存到 .env 文件中")
    print("✅ 程序会自动读取 .env 文件中的配置")
    print("✅ 无需手动设置环境变量")
    print("")
    print("🔧 如果需要手动修改配置：")
    print("   编辑 .env 文件，修改 JWT_SECRET_KEY 的值")
    print("")
    print("🔍 当前配置的密钥：")
    print(f"   {key[:20]}...{key[-10:]} (长度: {len(key)})")

def create_env_file(key):
    """创建 .env 文件"""
    env_file = ".env"
    print(f"\n📄 创建 {env_file} 文件...")
    
    try:
        with open(env_file, 'w', encoding='utf-8') as f:
            f.write(f"# ProxyPool 环境变量配置\n")
            f.write(f"# 生成时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"JWT_SECRET_KEY={key}\n")
        
        print(f"✅ 已创建 {env_file} 文件")
        print("💡 提示: 请将 .env 文件添加到 .gitignore 中，避免提交到版本控制")
        
    except Exception as e:
        print(f"❌ 创建 {env_file} 文件失败: {e}")

def test_configuration():
    """测试配置"""
    print("\n🧪 测试配置...")
    
    try:
        # 尝试导入配置
        sys.path.insert(0, os.path.dirname(__file__))
        from config import JWT_SECRET_KEY
        
        print("✅ 配置导入成功")
        print(f"✅ JWT密钥长度: {len(JWT_SECRET_KEY)}")
        
        if len(JWT_SECRET_KEY) >= 32:
            print("✅ 安全配置验证通过")
            return True
        else:
            print("❌ 密钥长度不足")
            return False
            
    except Exception as e:
        print(f"❌ 配置测试失败: {e}")
        return False

def main():
    """主函数"""
    print_banner()
    
    # 检查当前配置
    check_current_config()
    
    # 生成新密钥
    new_key = generate_new_key()
    
    # 显示设置命令
    show_setup_commands(new_key)
    
    # 创建 .env 文件
    create_env_file(new_key)
    
    # 测试配置
    print("\n🧪 测试配置...")
    if test_configuration():
        print("\n🎉 安全配置完成！")
        print("✅ 现在可以安全地运行 ProxyPool 了")
        print("\n💡 提示：")
        print("   - 配置已保存到 .env 文件中")
        print("   - 直接运行: python main.py")
    else:
        print("\n⚠️  配置测试失败，请检查设置")

if __name__ == "__main__":
    main()
