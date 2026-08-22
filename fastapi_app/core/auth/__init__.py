"""认证子包（core/deps 拆分子模块）。

- token:     JWT 编解码（签发/校验）
- blacklist: token 黑名单/撤销（Redis + 本地 LRU 降级）

core/deps 保留为 Facade，re-export 全部公共符号以保持向后兼容。
"""
