"""简单的数据清空脚本（已归档 —— 审计 F1-6 / P1-35）。

原实现
------
按模块硬编码一份表清单逐表 DELETE：无备份、无写护栏、无保留表校验。

归档原因
--------
审计实测该清单与 ORM metadata 漂移，漏清板房 7 张、湖北外发 5 张、
notification / numbering_counter 等表；dry-run 也不显示这些残留，运维无从察觉。
原实现见 git 历史（本文件移动到 scripts/archive/ 之前的版本）。

现状
----
本文件已改为**拒绝执行**的占位脚本：任何调用都直接退出（exit 2）并指向
``scripts/purge_simulated_data.py`` —— 上线清库唯一入口（pg_dump 备份 +
保留表指纹复核 + 真 dry-run + 统一写护栏），表清单来自 ``scripts/purge_scope.py``。

替代路径
--------
- 上线清库：``python scripts/purge_simulated_data.py --dry-run`` / ``--execute``
- 开发期全量清空：``python scripts/clear_all_data.py --dry-run`` / ``--execute``

两者都在启动时对照 ORM metadata 做 fail-closed 覆盖校验，新增 ORM 表而未分类
即拒绝执行 —— 漏表不再静默。
"""
import sys


def main():
    print('本脚本已归档：表清单曾与 ORM 漂移，且无备份 / 保留表复核 / 写护栏。')
    print('上线清库请用 scripts/purge_simulated_data.py（备份 + 复核 + 真 dry-run + 写护栏）。')
    print('开发期全量清空请用 scripts/clear_all_data.py --dry-run 预览。')
    sys.exit(2)


if __name__ == '__main__':
    main()
