"""
Trae AI Agent System v2.0 - 端到端测试套件
验证所有配置文件的加载、验证和集成
"""
import json
import os
import pytest
from pathlib import Path
from typing import Dict, Any, List

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
CORE_DIR = BASE_DIR / "core"
MONITORING_DIR = BASE_DIR / "monitoring"


class ConfigValidator:
    """配置文件验证器"""
    
    REQUIRED_FIELDS = {
        "version": str,
        "name": str
    }
    
    REQUIRED_FIELDS_WITH_ENABLED = {
        "version": str,
        "name": str,
        "enabled": bool
    }
    
    @staticmethod
    def load_json(file_path: Path) -> Dict[str, Any]:
        """加载JSON配置文件"""
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @staticmethod
    def validate_required_fields(config: Dict[str, Any], require_enabled: bool = False) -> List[str]:
        """验证必需字段"""
        errors = []
        fields = ConfigValidator.REQUIRED_FIELDS_WITH_ENABLED if require_enabled else ConfigValidator.REQUIRED_FIELDS
        for field, expected_type in fields.items():
            if field not in config:
                errors.append(f"Missing required field: {field}")
            elif not isinstance(config[field], expected_type):
                errors.append(f"Field '{field}' should be {expected_type.__name__}, got {type(config[field]).__name__}")
        return errors
    
    @staticmethod
    def validate_config_path(config: Dict[str, Any], path_key: str = "configPath") -> List[str]:
        """验证配置文件路径是否存在"""
        errors = []
        if path_key in config:
            config_path = Path(str(config[path_key]))
            if config_path.is_absolute():
                full_path = config_path
            else:
                full_path = BASE_DIR.parent / config_path
            if not full_path.exists():
                errors.append(f"Config path not found: {full_path}")
        return errors


class TestConfigFilesExist:
    """测试配置文件是否存在"""
    
    def test_main_config_exists(self):
        """主配置文件存在"""
        config_path = CONFIG_DIR / "agent-system-v2.json"
        assert config_path.exists(), f"Main config file not found: {config_path}"
    
    def test_query_guard_config_exists(self):
        """QueryGuard配置文件存在"""
        config_path = CORE_DIR / "query-engine" / "query-guard.json"
        assert config_path.exists(), f"QueryGuard config not found: {config_path}"
    
    def test_hooks_config_exists(self):
        """Hooks配置文件存在"""
        config_path = CORE_DIR / "query-engine" / "hooks.json"
        assert config_path.exists(), f"Hooks config not found: {config_path}"
    
    def test_circuit_breaker_config_exists(self):
        """CircuitBreaker配置文件存在"""
        config_path = CORE_DIR / "transport" / "circuit-breaker.json"
        assert config_path.exists(), f"CircuitBreaker config not found: {config_path}"
    
    def test_retry_policy_config_exists(self):
        """RetryPolicy配置文件存在"""
        config_path = CORE_DIR / "transport" / "retry-policy.json"
        assert config_path.exists(), f"RetryPolicy config not found: {config_path}"
    
    def test_hybrid_transport_config_exists(self):
        """HybridTransport配置文件存在"""
        config_path = CORE_DIR / "transport" / "hybrid-transport.json"
        assert config_path.exists(), f"HybridTransport config not found: {config_path}"
    
    def test_hot_reloader_config_exists(self):
        """HotReloader配置文件存在"""
        config_path = CORE_DIR / "skills" / "hot-reloader.json"
        assert config_path.exists(), f"HotReloader config not found: {config_path}"
    
    def test_performance_config_exists(self):
        """Performance配置文件存在"""
        config_path = MONITORING_DIR / "performance.json"
        assert config_path.exists(), f"Performance config not found: {config_path}"


class TestMainConfigValidation:
    """主配置文件验证测试"""
    
    @pytest.fixture
    def main_config(self):
        """加载主配置文件"""
        return ConfigValidator.load_json(CONFIG_DIR / "agent-system-v2.json")
    
    def test_version_format(self, main_config):
        """版本号格式正确"""
        assert "version" in main_config
        version = main_config["version"]
        parts = version.split(".")
        assert len(parts) == 3, f"Version should be semver format: {version}"
    
    def test_required_fields(self, main_config):
        """必需字段存在"""
        errors = ConfigValidator.validate_required_fields(main_config)
        assert len(errors) == 0, f"Validation errors: {errors}"
    
    def test_query_engine_enabled(self, main_config):
        """QueryEngine模块启用"""
        assert main_config.get("queryEngine", {}).get("enabled") == True
    
    def test_transport_enabled(self, main_config):
        """Transport模块启用"""
        assert main_config.get("transport", {}).get("enabled") == True
    
    def test_monitoring_enabled(self, main_config):
        """Monitoring模块启用"""
        assert main_config.get("monitoring", {}).get("performance", {}).get("enabled") == True
    
    def test_config_paths_valid(self, main_config):
        """配置文件路径有效"""
        errors = []
        
        if "queryEngine" in main_config:
            if "queryGuard" in main_config["queryEngine"]:
                errors.extend(ConfigValidator.validate_config_path(main_config["queryEngine"]["queryGuard"]))
            if "hooks" in main_config["queryEngine"]:
                errors.extend(ConfigValidator.validate_config_path(main_config["queryEngine"]["hooks"]))
        
        if "transport" in main_config:
            for key in ["circuitBreaker", "retryPolicy", "hybridTransport"]:
                if key in main_config["transport"]:
                    errors.extend(ConfigValidator.validate_config_path(main_config["transport"][key]))
        
        if "skills" in main_config and "hotReload" in main_config["skills"]:
            errors.extend(ConfigValidator.validate_config_path(main_config["skills"]["hotReload"]))
        
        if "monitoring" in main_config and "performance" in main_config["monitoring"]:
            errors.extend(ConfigValidator.validate_config_path(main_config["monitoring"]["performance"]))
        
        assert len(errors) == 0, f"Invalid config paths: {errors}"


class TestQueryGuardConfig:
    """QueryGuard配置验证测试"""
    
    @pytest.fixture
    def query_guard_config(self):
        return ConfigValidator.load_json(CORE_DIR / "query-engine" / "query-guard.json")
    
    def test_rate_limiting_configured(self, query_guard_config):
        """速率限制配置正确"""
        rate_limiting = query_guard_config.get("rateLimiting", {})
        assert rate_limiting.get("enabled") == True
        assert "global" in rate_limiting
        assert "maxRequestsPerMinute" in rate_limiting["global"]
    
    def test_input_validation_configured(self, query_guard_config):
        """输入验证配置正确"""
        input_validation = query_guard_config.get("inputValidation", {})
        assert input_validation.get("enabled") == True
        assert "maxLength" in input_validation
        assert "blockedPatterns" in input_validation
    
    def test_malware_detection_configured(self, query_guard_config):
        """恶意检测配置正确"""
        malware = query_guard_config.get("malwareDetection", {})
        assert malware.get("enabled") == True
        assert "checkPatterns" in malware


class TestCircuitBreakerConfig:
    """CircuitBreaker配置验证测试"""
    
    @pytest.fixture
    def circuit_breaker_config(self):
        return ConfigValidator.load_json(CORE_DIR / "transport" / "circuit-breaker.json")
    
    def test_global_settings(self, circuit_breaker_config):
        """全局设置正确"""
        global_config = circuit_breaker_config.get("global", {})
        assert "failureThreshold" in global_config
        assert "timeout" in global_config
        assert global_config["failureThreshold"] > 0
        assert global_config["timeout"] > 0
    
    def test_per_transport_settings(self, circuit_breaker_config):
        """每个传输协议都有设置"""
        per_transport = circuit_breaker_config.get("perTransport", {})
        expected_transports = ["websocket", "http", "sse", "mcp"]
        for transport in expected_transports:
            assert transport in per_transport, f"Missing config for transport: {transport}"


class TestRetryPolicyConfig:
    """RetryPolicy配置验证测试"""
    
    @pytest.fixture
    def retry_policy_config(self):
        return ConfigValidator.load_json(CORE_DIR / "transport" / "retry-policy.json")
    
    def test_global_settings(self, retry_policy_config):
        """全局设置正确"""
        global_config = retry_policy_config.get("global", {})
        assert global_config.get("maxRetries", 0) >= 1
        assert global_config.get("initialDelay", 0) > 0
        assert global_config.get("backoffMultiplier", 0) >= 1
    
    def test_retryable_errors_defined(self, retry_policy_config):
        """可重试错误已定义"""
        retryable = retry_policy_config.get("retryableErrors", [])
        assert len(retryable) > 0
        assert "ETIMEDOUT" in retryable
    
    def test_non_retryable_errors_defined(self, retry_policy_config):
        """不可重试错误已定义"""
        non_retryable = retry_policy_config.get("nonRetryableErrors", [])
        assert len(non_retryable) > 0
        assert "404 Not Found" in non_retryable


class TestHybridTransportConfig:
    """HybridTransport配置验证测试"""
    
    @pytest.fixture
    def hybrid_transport_config(self):
        return ConfigValidator.load_json(CORE_DIR / "transport" / "hybrid-transport.json")
    
    def test_transports_configured(self, hybrid_transport_config):
        """传输协议配置正确"""
        transports = hybrid_transport_config.get("transports", {})
        expected = ["websocket", "http", "sse", "mcp"]
        for transport in expected:
            assert transport in transports, f"Missing transport: {transport}"
            assert transports[transport].get("enabled") == True
    
    def test_failover_configured(self, hybrid_transport_config):
        """故障转移配置正确"""
        failover = hybrid_transport_config.get("failover", {})
        assert failover.get("enabled") == True
        assert "fallbackOrder" in failover
        assert len(failover["fallbackOrder"]) > 0
    
    def test_health_check_configured(self, hybrid_transport_config):
        """健康检查配置正确"""
        health_check = hybrid_transport_config.get("healthCheck", {})
        assert health_check.get("enabled") == True
        assert "interval" in health_check
        assert "timeout" in health_check


class TestHooksConfig:
    """Hooks配置验证测试"""
    
    @pytest.fixture
    def hooks_config(self):
        return ConfigValidator.load_json(CORE_DIR / "query-engine" / "hooks.json")
    
    def test_pre_execute_hooks(self, hooks_config):
        """前置执行钩子配置正确"""
        hooks = hooks_config.get("hooks", {}).get("preExecute", [])
        assert len(hooks) > 0
        
        permission_check = next((h for h in hooks if h["name"] == "permission-check"), None)
        assert permission_check is not None
        assert permission_check.get("required") == True
    
    def test_post_execute_hooks(self, hooks_config):
        """后置执行钩子配置正确"""
        hooks = hooks_config.get("hooks", {}).get("postExecute", [])
        assert len(hooks) > 0
    
    def test_error_hooks(self, hooks_config):
        """错误处理钩子配置正确"""
        hooks = hooks_config.get("hooks", {}).get("onError", [])
        assert len(hooks) > 0
        
        error_classification = next((h for h in hooks if h["name"] == "error-classification"), None)
        assert error_classification is not None
        assert error_classification.get("required") == True
    
    def test_timeout_hooks(self, hooks_config):
        """超时处理钩子配置正确"""
        hooks = hooks_config.get("hooks", {}).get("onTimeout", [])
        assert len(hooks) > 0


class TestPerformanceConfig:
    """Performance配置验证测试"""
    
    @pytest.fixture
    def performance_config(self):
        return ConfigValidator.load_json(MONITORING_DIR / "performance.json")
    
    def test_metrics_configured(self, performance_config):
        """指标配置正确"""
        metrics = performance_config.get("metrics", {})
        assert metrics.get("collectInterval", 0) > 0
        assert metrics.get("retentionDays", 0) > 0
    
    def test_alerts_configured(self, performance_config):
        """告警配置正确"""
        alerts = performance_config.get("alerts", {})
        assert alerts.get("enabled") == True
        assert len(alerts.get("rules", [])) > 0
    
    def test_dashboard_configured(self, performance_config):
        """仪表盘配置正确"""
        dashboard = performance_config.get("dashboard", {})
        assert dashboard.get("enabled") == True
        assert "refreshInterval" in dashboard


class TestHotReloaderConfig:
    """HotReloader配置验证测试"""
    
    @pytest.fixture
    def hot_reloader_config(self):
        return ConfigValidator.load_json(CORE_DIR / "skills" / "hot-reloader.json")
    
    def test_watcher_configured(self, hot_reloader_config):
        """监听器配置正确"""
        watcher = hot_reloader_config.get("watcher", {})
        assert len(watcher.get("watchDirectories", [])) > 0
        assert watcher.get("debounceMs", 0) > 0
    
    def test_hot_reload_enabled(self, hot_reloader_config):
        """热重载启用"""
        hot_reload = hot_reloader_config.get("hotReload", {})
        assert hot_reload.get("enabled") == True
    
    def test_skill_discovery_configured(self, hot_reloader_config):
        """技能发现配置正确"""
        discovery = hot_reloader_config.get("skillDiscovery", {})
        assert discovery.get("autoDiscover") == True


class TestConfigIntegration:
    """配置集成测试"""
    
    def test_all_configs_loadable(self):
        """所有配置文件可加载"""
        config_files = [
            CONFIG_DIR / "agent-system-v2.json",
            CORE_DIR / "query-engine" / "query-guard.json",
            CORE_DIR / "query-engine" / "hooks.json",
            CORE_DIR / "transport" / "circuit-breaker.json",
            CORE_DIR / "transport" / "retry-policy.json",
            CORE_DIR / "transport" / "hybrid-transport.json",
            CORE_DIR / "skills" / "hot-reloader.json",
            MONITORING_DIR / "performance.json",
        ]
        
        for config_file in config_files:
            config = ConfigValidator.load_json(config_file)
            assert config is not None
            assert isinstance(config, dict)
    
    def test_version_consistency(self):
        """版本号一致性"""
        main_config = ConfigValidator.load_json(CONFIG_DIR / "agent-system-v2.json")
        main_version = main_config.get("version")
        
        config_files = [
            CORE_DIR / "query-engine" / "query-guard.json",
            CORE_DIR / "transport" / "circuit-breaker.json",
            CORE_DIR / "skills" / "hot-reloader.json",
            MONITORING_DIR / "performance.json",
        ]
        
        for config_file in config_files:
            config = ConfigValidator.load_json(config_file)
            assert config.get("version") == main_version, \
                f"Version mismatch in {config_file.name}: expected {main_version}, got {config.get('version')}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
