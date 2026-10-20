"""数据清理脚本 - 保留用户管理数据，清除其他所有数据（已归档 —— 审计 F1-6 / P1-35）。

原实现
------
保留 user / permission / user_permission，清空其余数据库表，并**顺带删除
``logs/`` 下的日志文件**、清理 Redis 缓存与临时文件。

归档原因
--------
- CLEAR_TABLES_ORDERED 与 ORM metadata 漂移（漏板房 7 张、湖北外发 5 张、
  notification / numbering_counter 等），而 verify() 只校验自己的清单，
  仍会打印「其他数据已彻底清除」—— 静默残留 + 虚假结论；
- 删日志文件的副作用会误伤审计线索；
- 无备份、无写护栏、无保留表指纹复核。

原实现见 git 历史（本文件移动到 scripts/archive/ 之前的版本）。

现状
----
本文件已改为**拒绝执行**的占位脚本：任何调用都直接退出（exit 2）并指向
``scripts/purge_simulated_data.py`` —— 上线清库唯一入口（pg_dump 备份 +
保留表指纹复核 + 真 dry-run + 统一写护栏），表清单来自 ``scripts/purge_scope.py``。

替代路径
--------
- 上线清库（保留用户 / 客户 / 运行配置）：
  ``python scripts/purge_simulated_data.py --dry-run`` / ``--execute``
- 开发期清业务数据但**保留用户**（避免把自己锁在门外）：
  ``python scripts/purge_simulated_data.py --scope DEV_KEEP_USERS --dry-run``
"""
import sys


def main():
    print('本脚本已归档：表清单曾与 ORM 漂移（漏 28 张），却打印「其他数据已彻底清除」；')
    print('且会顺带删除 logs/ 下的日志文件。')
    print('请改用 scripts/purge_simulated_data.py（备份 + 复核 + 真 dry-run + 写护栏）。')
    print('开发期保留用户清业务数据：--scope DEV_KEEP_USERS。')
    sys.exit(2)


if __name__ == '__main__':
    main()
