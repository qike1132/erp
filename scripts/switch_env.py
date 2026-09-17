"""
环境切换脚本
用于在开发环境和生产环境之间切换
"""
import shutil
import sys
from pathlib import Path


def switch_environment(env_type):
    """
    切换环境配置

    Args:
        env_type: 'development' 或 'production'
    """
    project_root = Path(__file__).parent
    env_file = project_root / '.env'
    env_dev = project_root / '.env.development'
    env_prod = project_root / '.env.production'

    if env_type == 'development':
        source_file = env_dev
        env_name = '开发环境'
    elif env_type == 'production':
        # 生产切换已禁用：.env.production 是全 ${VAR} 占位模板（真实密钥由
        # NSSM 服务环境变量注入），用它覆盖 .env 会让应用拿着字面占位符启动即崩。
        # 生产模式的正确入口：ERP 服务器管理器 GUI 的「生产模式」（NSSM erp-prod）。
        print("❌ 错误: 生产环境切换已禁用（本脚本仅用于开发环境）")
        print("   原因: .env.production 为占位模板，覆盖 .env 会导致全站启动失败")
        print("   正确方式: 使用 ERP 服务器管理器 GUI 切换到「生产模式」（NSSM 托管）")
        return False
    else:
        print(f"❌ 错误: 不支持的环境类型 '{env_type}'")
        print("   支持的环境: development, production")
        return False

    if not source_file.exists():
        print(f"❌ 错误: 配置文件不存在: {source_file}")
        return False

    try:
        # 备份当前配置
        if env_file.exists():
            backup_file = project_root / '.env.backup'
            shutil.copy2(env_file, backup_file)
            print(f"✅ 已备份当前配置到: {backup_file}")

        # 复制新配置
        shutil.copy2(source_file, env_file)
        print(f"✅ 已切换到 {env_name}")
        print(f"   配置文件: {source_file}")

        # 显示关键配置
        print("\n📋 当前环境配置:")
        print(f"   APP_ENV: {env_type}")
        print(f"   APP_DEBUG: {'1' if env_type == 'development' else '0'}")

        # 启动建议
        print("\n启动命令:")
        if env_type == 'development':
            print("   python run.py")
        else:
            print("   uvicorn fastapi_app.main:app --host 0.0.0.0 --port 5002")

        return True

    except Exception as e:
        print(f"❌ 切换失败: {e}")
        return False

def show_current_env():
    """显示当前环境配置"""
    project_root = Path(__file__).parent
    env_file = project_root / '.env'

    if not env_file.exists():
        print("❌ 当前没有配置文件 (.env)")
        return

    print("=" * 50)
    print("当前环境配置")
    print("=" * 50)

    with open(env_file, encoding='utf-8') as f:
        lines = f.readlines()

    # 显示关键配置
    key_configs = [
        'APP_ENV',
        'APP_DEBUG',
        'DB_HOST',
        'DB_NAME',
        'REDIS_HOST',
        'CACHE_TYPE'
    ]

    for line in lines:
        line = line.strip()
        if any(line.startswith(key) for key in key_configs):
            print(f"   {line}")

    print("=" * 50)

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("=" * 50)
        print("ERP系统环境切换工具")
        print("=" * 50)
        print("\n用法:")
        print("  python switch_env.py <环境类型>")
        print("\n环境类型:")
        print("  development  - 开发环境")
        print("  production   - 生产环境")
        print("  show         - 显示当前环境")
        print("\n示例:")
        print("  python switch_env.py development")
        print("  python switch_env.py production")
        print("  python switch_env.py show")
        print("=" * 50)
        return

    command = sys.argv[1].lower()

    if command == 'show':
        show_current_env()
    elif command in ['development', 'production']:
        switch_environment(command)
    else:
        print(f"❌ 错误: 未知的命令 '{command}'")
        print("   支持的命令: development, production, show")

if __name__ == '__main__':
    main()
