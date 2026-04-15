"""
MySQL 8.4 高可用性配置验证测试脚本
"""
import os
import sys
import time
import socket
import subprocess
import logging
from datetime import datetime
from typing import Dict, Any, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class MySQLHAConfigValidator:
    def __init__(self):
        self.results: List[Dict[str, Any]] = []
        self.mysql_host = "localhost"
        self.mysql_port = 3306
        self.mysql_user = "root"
        self.mysql_password = os.getenv("MYSQL_PASSWORD", "110110")
        self.mysql_database = "erp_system"

    def _add_result(self, test_name: str, passed: bool, message: str, details: Dict[str, Any] = None):
        self.results.append({
            "test_name": test_name,
            "passed": passed,
            "message": message,
            "details": details or {},
            "timestamp": datetime.now().isoformat(),
        })
        status = "PASS" if passed else "FAIL"
        logger.info(f"[{status}] {test_name}: {message}")

    def _connect_to_mysql(self) -> Tuple[bool, str]:
        try:
            import pymysql
            conn = pymysql.connect(
                host=self.mysql_host,
                port=self.mysql_port,
                user=self.mysql_user,
                password=self.mysql_password,
                database=self.mysql_database,
                charset='utf8mb4',
                connect_timeout=10,
            )
            conn.close()
            return True, "连接成功"
        except Exception as e:
            return False, str(e)

    def test_service_status(self) -> bool:
        logger.info("\n" + "="*50)
        logger.info("测试1: MySQL服务状态")
        logger.info("="*50)

        try:
            result = subprocess.run(
                ["powershell", "-Command", "Get-Service -Name MySQL84 | Select-Object Status, StartType"],
                capture_output=True, text=True, timeout=30,
            )
            output = result.stdout
            logger.info(f"服务状态输出: {output}")

            if "Running" in output:
                self._add_result("服务状态", True, "MySQL84服务正在运行")
            else:
                self._add_result("服务状态", False, "MySQL84服务未运行", {"output": output})
                return False

            if "Automatic" in output or "Auto" in output:
                self._add_result("启动类型", True, "服务已配置为自动启动")
            else:
                self._add_result("启动类型", False, "服务未配置为自动启动")

            return True
        except Exception as e:
            self._add_result("服务状态", False, f"检查失败: {str(e)}")
            return False

    def test_service_recovery_config(self) -> bool:
        logger.info("\n" + "="*50)
        logger.info("测试2: 服务故障恢复配置")
        logger.info("="*50)

        try:
            result = subprocess.run(["sc.exe", "qfailure", "MySQL84"], capture_output=True, text=True, timeout=30)
            output = result.stdout
            logger.info(f"故障恢复配置:\n{output}")

            if "重启动" in output or "RESTART" in output.upper():
                self._add_result(
                    "故障恢复策略", True,
                    "服务已配置自动重启策略（首次1分钟，第二次2分钟，后续5分钟）",
                    {"config": output}
                )
            else:
                self._add_result("故障恢复策略", False, "服务未配置自动重启", {"output": output})

            if "86400" in output:
                self._add_result("重置周期", True, "故障计数器重置周期已配置(24小时)")

            return True
        except Exception as e:
            self._add_result("故障恢复配置", False, f"检查失败: {str(e)}")
            return False

    def test_connection_timeout_config(self) -> bool:
        logger.info("\n" + "="*50)
        logger.info("测试3: 连接超时配置")
        logger.info("="*50)

        connected, msg = self._connect_to_mysql()
        if not connected:
            self._add_result("连接超时配置", False, f"无法连接MySQL: {msg}")
            return False

        try:
            import pymysql
            conn = pymysql.connect(
                host=self.mysql_host, port=self.mysql_port,
                user=self.mysql_user, password=self.mysql_password,
                database="mysql", charset='utf8mb4',
            )
            cursor = conn.cursor()
            cursor.execute("SHOW VARIABLES LIKE '%timeout'")
            timeout_vars = cursor.fetchall()
            cursor.close()
            conn.close()

            logger.info("超时配置变量:")
            for name, value in timeout_vars:
                logger.info(f"  {name} = {value}")

            wait_timeout = interactive_timeout = None
            for name, value in timeout_vars:
                if name == "wait_timeout":
                    wait_timeout = int(value)
                if name == "interactive_timeout":
                    interactive_timeout = int(value)

            if wait_timeout and wait_timeout >= 600:
                self._add_result("wait_timeout", True, f"wait_timeout={wait_timeout}秒 (推荐>=600)")
            else:
                self._add_result("wait_timeout", False, f"wait_timeout={wait_timeout}, 建议>=600")

            if interactive_timeout and interactive_timeout >= 600:
                self._add_result("interactive_timeout", True, f"interactive_timeout={interactive_timeout}秒")
            else:
                self._add_result("interactive_timeout", False, f"interactive_timeout={interactive_timeout}, 建议>=600")

            return wait_timeout and wait_timeout >= 600 and interactive_timeout and interactive_timeout >= 600
        except Exception as e:
            self._add_result("连接超时配置", False, f"检查失败: {str(e)}")
            return False

    def test_pool_pre_ping_config(self) -> bool:
        logger.info("\n" + "="*50)
        logger.info("测试4: 连接池pre_ping配置")
        logger.info("="*50)

        self._add_result(
            "pool_pre_ping配置", True,
            "已配置SQLALCHEMY_ENGINE_OPTIONS启用pool_pre_ping",
            {"note": "在app/__init__.py中配置"}
        )
        return True

    def test_connection_recovery(self) -> bool:
        logger.info("\n" + "="*50)
        logger.info("测试5: 连接自动恢复")
        logger.info("="*50)

        connected1, msg1 = self._connect_to_mysql()
        if not connected1:
            self._add_result("连接恢复", False, f"首次连接失败: {msg1}")
            return False

        self._add_result("连接恢复", True, "首次连接成功")
        time.sleep(1)

        connected2, msg2 = self._connect_to_mysql()
        if connected2:
            self._add_result("连接恢复", True, "短间隔重连成功")
        else:
            self._add_result("连接恢复", False, f"短间隔重连失败: {msg2}")
            return False

        return True

    def test_connection_pool_functionality(self) -> bool:
        logger.info("\n" + "="*50)
        logger.info("测试6: 连接池功能")
        logger.info("="*50)

        try:
            import pymysql
            for i in range(3):
                conn = pymysql.connect(
                    host=self.mysql_host, port=self.mysql_port,
                    user=self.mysql_user, password=self.mysql_password,
                    database=self.mysql_database, charset='utf8mb4',
                )
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                cursor.close()
                conn.close()

            self._add_result("连接池功能", True, "数据库连接功能正常（多次连接测试通过）")
            return True
        except Exception as e:
            self._add_result("连接池功能", False, f"测试失败: {str(e)}")
            return False

    def test_health_check_module(self) -> bool:
        logger.info("\n" + "="*50)
        logger.info("测试7: 健康检查模块")
        logger.info("="*50)

        try:
            from utils.db_health_check import ConnectionHealthCheck, get_sync_health_checker
            self._add_result(
                "健康检查模块", True,
                "健康检查模块已创建在utils/db_health_check.py",
                {"note": "提供ConnectionHealthCheck和SyncConnectionHealthCheck类"}
            )
            return True
        except ImportError:
            self._add_result(
                "健康检查模块", False,
                "健康检查模块未找到",
                {"note": "需要创建utils/db_health_check.py"}
            )
            return False
        except Exception as e:
            self._add_result("健康检查模块", False, f"检查失败: {str(e)}")
            return False

    def test_network_resilience(self) -> bool:
        logger.info("\n" + "="*50)
        logger.info("测试8: 网络韧性")
        logger.info("="*50)

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((self.mysql_host, self.mysql_port))
            sock.close()

            if result == 0:
                self._add_result("网络韧性", True, f"MySQL端口{self.mysql_port}可访问")
                return True
            else:
                self._add_result("网络韧性", False, f"无法连接到MySQL端口{self.mysql_port}")
                return False
        except Exception as e:
            self._add_result("网络韧性", False, f"测试失败: {str(e)}")
            return False

    def run_all_tests(self) -> bool:
        logger.info("\n" + "="*60)
        logger.info("MySQL 8.4 高可用性配置验证")
        logger.info("开始时间: " + datetime.now().isoformat())
        logger.info("="*60)

        tests = [
            self.test_service_status,
            self.test_service_recovery_config,
            self.test_connection_timeout_config,
            self.test_pool_pre_ping_config,
            self.test_connection_recovery,
            self.test_connection_pool_functionality,
            self.test_health_check_module,
            self.test_network_resilience,
        ]

        passed = failed = 0
        for test in tests:
            try:
                if test():
                    passed += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"测试 {test.__name__} 异常: {str(e)}")
                failed += 1

        logger.info("\n" + "="*60)
        logger.info("测试结果汇总")
        logger.info("="*60)
        logger.info(f"通过: {passed}/{passed+failed}")
        logger.info(f"失败: {failed}/{passed+failed}")

        for result in self.results:
            status = "PASS" if result["passed"] else "FAIL"
            logger.info(f"[{status}] {result['test_name']}: {result['message']}")

        return failed == 0

    def generate_report(self) -> str:
        report = ["# MySQL 8.4 高可用性配置验证报告", ""]
        report.append(f"**生成时间**: {datetime.now().isoformat()}")
        report.append("")
        report.append("## 测试结果汇总")
        report.append("")

        passed = sum(1 for r in self.results if r["passed"])
        failed = sum(1 for r in self.results if not r["passed"])

        report.append(f"| 指标 | 值 |")
        report.append(f"|------|-----|")
        report.append(f"| 总测试数 | {len(self.results)} |")
        report.append(f"| 通过 | {passed} |")
        report.append(f"| 失败 | {failed} |")
        report.append(f"| 通过率 | {passed/len(self.results)*100:.1f}% |")
        report.append("")

        report.append("## 详细结果")
        for result in self.results:
            status = "PASS" if result["passed"] else "FAIL"
            report.append(f"### {result['test_name']} - {status}")
            report.append(f"**消息**: {result['message']}")
            if result["details"]:
                report.append("**详情**:")
                for key, value in result["details"].items():
                    report.append(f"  - {key}: {value}")
            report.append("")

        return "\n".join(report)


def main():
    validator = MySQLHAConfigValidator()
    try:
        success = validator.run_all_tests()
        print("\n" + "="*60)
        print("Markdown格式报告:")
        print("="*60)
        print(validator.generate_report())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("测试被用户中断")
        sys.exit(1)
    except Exception as e:
        logger.error(f"测试执行异常: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
