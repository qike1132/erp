"""
优化执行主程序
整合优化执行器和代码优化器,执行安全的代码优化
"""
import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from quality.optimizers.optimization_executor import OptimizationExecutor
from quality.optimizers.code_optimizer import run_all_optimizations


def main():
    """执行优化主程序"""
    project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    print("=" * 60)
    print("ERP系统代码优化执行")
    print("=" * 60)
    print(f"项目路径: {project_path}")
    print()
    
    # 创建优化执行器
    executor = OptimizationExecutor(project_path)
    
    # 查看当前状态
    print("当前状态:")
    status = executor.get_status()
    print(f"  备份总数: {status['total_backups']}")
    print(f"  最近变更: {len(status['recent_changes'])} 条")
    print()
    
    # 执行优化
    success = executor.execute_optimization(
        optimization_func=lambda: run_all_optimizations(project_path),
        description="代码风格优化和文档完善"
    )
    
    # 输出结果
    print("\n" + "=" * 60)
    if success:
        print("[SUCCESS] 优化执行成功!")
        print("   - 代码已优化")
        print("   - 测试验证通过")
        print("   - 变更已记录")
    else:
        print("[FAILED] 优化执行失败!")
        print("   已自动回滚到优化前状态")
    print("=" * 60)
    
    # 显示最终状态
    print("\n最终状态:")
    final_status = executor.get_status()
    print(f"  备份总数: {final_status['total_backups']}")
    
    if final_status['recent_changes']:
        print("\n最近变更:")
        for change in final_status['recent_changes'][-3:]:
            status_icon = "[OK]" if change['success'] else "[FAIL]"
            print(f"  {status_icon} {change['timestamp']} - {change['description']}")
    
    return success


if __name__ == '__main__':
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n用户中断执行")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n执行异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
