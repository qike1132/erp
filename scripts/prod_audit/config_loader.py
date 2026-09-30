"""配置加载器。

加载并校验 ``audit_config.yaml`` 与 ``rules_registry.yaml``,
返回强类型 pydantic 模型。

主要 API:
    - :meth:`ConfigLoader.load` — 加载审核配置
    - :meth:`RulesRegistry.load` — 加载规则注册表
    - :meth:`RulesRegistry.get_rule` — 查询单条规则
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from scripts.prod_audit.exceptions import AuditConfigError
from scripts.prod_audit.layers import LAYER_ORDER

# ---------------------------------------------------------------------------
# 常量与类型别名
# ---------------------------------------------------------------------------

_WEIGHT_SUM_TOLERANCE: float = 1.0e-9
"""权重求和校验浮点误差容忍度。"""

_EXPECTED_LAYERS: frozenset[str] = frozenset(LAYER_ORDER)
"""期望的 12 层 ID 集合。"""

# 阈值配置值类型(YAML 中阈值为异构类型:int / float / str / bool / list[str])
ThresholdValue = int | float | str | bool | list[str]


# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------


class LayerConfig(BaseModel):
    """单层审核配置。"""

    layer_id: str = Field(description="层唯一标识(L1-L12)")
    layer_name: str = Field(description="层名称")
    enabled: bool = Field(description="层开关")
    reviewer: str = Field(description="负责审核员")
    weight: float = Field(ge=0, le=1, description="层权重(0-1)")
    whitelist: list[str] = Field(default_factory=list, description="白名单文件路径列表")
    thresholds: dict[str, ThresholdValue] = Field(
        default_factory=dict, description="层阈值配置"
    )
    disable_reason: str | None = Field(
        default=None, description="禁用原因说明(enabled=false 时必填)"
    )

    @model_validator(mode="after")
    def _check_disable_reason(self) -> LayerConfig:
        if not self.enabled and not self.disable_reason:
            raise ValueError(
                f"Layer '{self.layer_id}' ({self.layer_name}) is disabled "
                "(enabled=false) but has no 'disable_reason' explanation field."
            )
        return self


class PerfThresholds(BaseModel):
    """压测阈值。"""

    core_list_p95_ms: int = Field(description="核心列表 P95 上限(ms)")
    aggregate_p95_ms: int = Field(description="聚合查询 P95 上限(ms)")
    min_rps: int = Field(description="最小并发吞吐量(RPS)")
    max_error_rate: float = Field(description="最大错误率")
    cold_start_s: int = Field(description="冷启动上限(秒)")
    max_memory_mb: int = Field(description="内存上限(MB)")
    max_conn_pool_util: float = Field(description="连接池利用率上限")
    lcp_s: float = Field(description="LCP 上限(秒)")
    fid_ms: int = Field(description="FID 上限(ms)")
    cls: float = Field(description="CLS 上限")
    max_bundle_size_mb: int = Field(description="产物体积上限(MB)")


class CoverageThresholds(BaseModel):
    """覆盖率分级阈值。"""

    core: int = Field(description="核心模块覆盖率下限(%)")
    backup: int = Field(description="备份模块覆盖率下限(%)")
    inbound: int = Field(description="来料模块覆盖率下限(%)")
    dashboard: int = Field(description="仪表盘模块覆盖率下限(%)")


class IssuePenalty(BaseModel):
    """各严重度问题扣分值。"""

    critical: int = Field(description="critical 问题扣分")
    high: int = Field(description="high 问题扣分")
    medium: int = Field(description="medium 问题扣分")
    low: int = Field(description="low 问题扣分")
    info: int = Field(description="info 问题扣分")


class WhitelistExplanation(BaseModel):
    """白名单豁免说明条目。"""

    file: str = Field(description="豁免文件路径")
    layer: str = Field(description="所属层 ID")
    rule_id: str = Field(description="关联规则 ID")
    count: int = Field(ge=0, description="豁免数量")
    reason: str = Field(description="豁免原因说明")


class AuditConfig(BaseModel):
    """审核流程配置(对应 ``audit_config.yaml``)。"""

    schema_version: str = Field(description="配置 schema 版本")
    weights: dict[str, float] = Field(description="12 层权重,key 为 layer_id")
    severity_threshold: str = Field(description="阻断上线严重度阈值")
    readiness_threshold: int = Field(description="生产就绪评分阈值")
    issue_penalty: IssuePenalty = Field(description="问题扣分配置")
    perf_thresholds: PerfThresholds = Field(description="压测阈值")
    coverage_thresholds: CoverageThresholds = Field(description="覆盖率阈值")
    resume_from: str | None = Field(default=None, description="断点恢复层 ID")
    whitelist_explanations: list[WhitelistExplanation] = Field(
        default_factory=list, description="白名单豁免说明"
    )
    layers: list[LayerConfig] = Field(
        description="12 层配置列表(按 L1-L12 顺序)"
    )

    @field_validator("severity_threshold")
    @classmethod
    def _validate_severity_threshold(cls, v: str) -> str:
        allowed = {"critical", "high", "medium", "low", "info"}
        if v not in allowed:
            raise ValueError(f"severity_threshold must be one of {allowed}, got '{v}'")
        return v

    @model_validator(mode="after")
    def _validate_weights_and_layers(self) -> AuditConfig:
        # 校验权重 key 集合
        weight_keys = set(self.weights.keys())
        if weight_keys != _EXPECTED_LAYERS:
            missing = _EXPECTED_LAYERS - weight_keys
            extra = weight_keys - _EXPECTED_LAYERS
            raise ValueError(f"weights keys mismatch: missing={missing}, extra={extra}")

        # 校验权重之和 = 1.0
        weight_sum = sum(self.weights.values())
        if abs(weight_sum - 1.0) > _WEIGHT_SUM_TOLERANCE:
            raise ValueError(
                f"weights sum must be 1.0 (tolerance {_WEIGHT_SUM_TOLERANCE}), "
                f"got {weight_sum}"
            )

        # 校验层配置: 12 层, layer_id 唯一且匹配 L1-L12
        layer_ids = [lc.layer_id for lc in self.layers]
        if len(layer_ids) != 12:
            raise ValueError(f"Expected 12 layer configs, got {len(layer_ids)}")
        layer_id_set = set(layer_ids)
        if layer_id_set != _EXPECTED_LAYERS:
            missing = _EXPECTED_LAYERS - layer_id_set
            extra = layer_id_set - _EXPECTED_LAYERS
            raise ValueError(f"layer_id mismatch: missing={missing}, extra={extra}")
        if len(layer_id_set) != len(layer_ids):
            raise ValueError("Duplicate layer_id in layers config")

        # 校验每层 weight 与 weights dict 一致
        for lc in self.layers:
            expected_weight = self.weights[lc.layer_id]
            if abs(lc.weight - expected_weight) > _WEIGHT_SUM_TOLERANCE:
                raise ValueError(
                    f"Layer {lc.layer_id} weight {lc.weight} != "
                    f"weights[{lc.layer_id}] {expected_weight}"
                )

        # 校验 resume_from(若指定)是合法层 ID
        if self.resume_from is not None and self.resume_from not in _EXPECTED_LAYERS:
            raise ValueError(
                f"resume_from must be one of {sorted(_EXPECTED_LAYERS)} or null, "
                f"got '{self.resume_from}'"
            )

        return self

    def get_layer(self, layer_id: str) -> LayerConfig:
        """按 layer_id 查询层配置。"""
        for lc in self.layers:
            if lc.layer_id == layer_id:
                return lc
        msg = f"Layer '{layer_id}' not found in config"
        raise KeyError(msg)

    def get_weight(self, layer_id: str) -> float:
        """返回指定层的权重。"""
        return self.weights[layer_id]


class RuleDefinition(BaseModel):
    """单条审核规则定义。"""

    rule_id: str = Field(description="规则唯一标识")
    version: str = Field(description="规则版本号")
    source: str = Field(description="来源依据")
    severity: str = Field(description="默认严重度")
    description: str = Field(description="规则描述")

    @field_validator("severity")
    @classmethod
    def _validate_severity(cls, v: str) -> str:
        allowed = {"critical", "high", "medium", "low", "info"}
        if v not in allowed:
            raise ValueError(f"severity must be one of {allowed}, got '{v}'")
        return v


class RulesRegistry(BaseModel):
    """审核规则注册表。

    加载 ``rules_registry.yaml``,提供按 ``rule_id`` 查询规则的能力。
    """

    schema_version: str = Field(description="注册表 schema 版本")
    rules: list[RuleDefinition] = Field(description="规则列表")

    @model_validator(mode="after")
    def _check_no_duplicate_rule_ids(self) -> RulesRegistry:
        seen: dict[str, int] = {}
        for rule in self.rules:
            if rule.rule_id in seen:
                raise ValueError(
                    f"Duplicate rule_id '{rule.rule_id}' "
                    f"(first at index {seen[rule.rule_id]})"
                )
            seen[rule.rule_id] = len(seen)
        return self

    @classmethod
    def load(cls, registry_path: str | Path) -> RulesRegistry:
        """加载 ``rules_registry.yaml`` 并校验规则 ID 唯一性。

        参数:
            registry_path: 规则注册表文件路径

        返回:
            :class:`RulesRegistry`

        抛出:
            AuditConfigError: 文件不存在 / 格式非法 / 规则 ID 重复
        """
        return ConfigLoader.load_rules(registry_path)

    def get_rule(self, rule_id: str) -> RuleDefinition:
        """按 ``rule_id`` 查询规则。

        参数:
            rule_id: 规则唯一标识

        返回:
            :class:`RuleDefinition`

        抛出:
            KeyError: 规则 ID 不存在
        """
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        msg = f"Rule '{rule_id}' not found in registry"
        raise KeyError(msg)

    def has_rule(self, rule_id: str) -> bool:
        """检查规则是否存在。"""
        return any(rule.rule_id == rule_id for rule in self.rules)


# ---------------------------------------------------------------------------
# 加载器
# ---------------------------------------------------------------------------


class ConfigLoader:
    """审核配置加载器。

    使用示例::

        config = ConfigLoader.load(Path("scripts/prod_audit/audit_config.yaml"))
        print(f"Loaded {len(config.layers)} layers")
    """

    @staticmethod
    def load(config_path: str | Path) -> AuditConfig:
        """加载 ``audit_config.yaml`` 并校验合法性。

        参数:
            config_path: 配置文件路径

        返回:
            :class:`AuditConfig`

        抛出:
            AuditConfigError: 文件不存在 / 格式非法 / Σweight ≠ 1 / 层配置缺失
        """
        path = Path(config_path)
        if not path.exists():
            raise AuditConfigError(f"Config file not found: {path}")

        try:
            raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise AuditConfigError(f"Failed to parse YAML config '{path}': {exc}") from exc

        if not isinstance(raw, Mapping):
            raise AuditConfigError(
                f"Config root must be a mapping, got {type(raw).__name__}"
            )

        # 将 YAML 中 layers dict 转换为 list, 注入 layer_id 和 weight
        config_dict = dict(raw)
        layers_raw = config_dict.get("layers", {})
        weights_raw = config_dict.get("weights", {})
        if isinstance(layers_raw, Mapping):
            layer_list: list[dict[str, object]] = []
            for layer_id in LAYER_ORDER:
                layer_cfg = dict(layers_raw.get(layer_id, {}))
                layer_cfg["layer_id"] = layer_id
                layer_cfg["weight"] = weights_raw.get(layer_id, 0.0)
                layer_list.append(layer_cfg)
            config_dict["layers"] = layer_list

        try:
            return AuditConfig.model_validate(config_dict)
        except Exception as exc:
            raise AuditConfigError(f"Config validation failed for '{path}': {exc}") from exc

    @staticmethod
    def load_rules(registry_path: str | Path) -> RulesRegistry:
        """加载 ``rules_registry.yaml`` 并校验规则 ID 唯一性。

        参数:
            registry_path: 规则注册表文件路径

        返回:
            :class:`RulesRegistry`

        抛出:
            AuditConfigError: 文件不存在 / 格式非法 / 规则 ID 重复
        """
        path = Path(registry_path)
        if not path.exists():
            raise AuditConfigError(f"Rules registry file not found: {path}")

        try:
            raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise AuditConfigError(
                f"Failed to parse YAML rules registry '{path}': {exc}"
            ) from exc

        if not isinstance(raw, Mapping):
            raise AuditConfigError(
                f"Rules registry root must be a mapping, got {type(raw).__name__}"
            )

        try:
            return RulesRegistry.model_validate(dict(raw))
        except Exception as exc:
            raise AuditConfigError(
                f"Rules registry validation failed for '{path}': {exc}"
            ) from exc
