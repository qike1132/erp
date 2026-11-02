"""Add user.token_version for session revocation (B1)

Revision ID: pg_standalone_109_add_user_token_version
Revises: pg_standalone_108_drop_legacy_orphan_indexes
Create Date: 2026-11-02

背景
----
JWT 是无状态的：改密、改超管标记、改工厂、禁用之后，已签发的 access/refresh
token 一直在有效期内继续可用。refresh 还会按 now+7d 重算过期时间，实际是
无限滑动续签——被劫持的会话拿不到任何"踢下线"的手段。

本迁移加一列 `user.token_version`：

* 签发 token 时写入 ``tv`` 声明；
* 请求/刷新时与库里当前值比对，不一致即 401；
* 改密等敏感变更把它 +1。

**旧 token 不带 ``tv``，按 0 处理**，因此本迁移上线本身不会把在线用户踢下线；
只有被主动 bump 的那个用户（或整库恢复后的全员）会失效。

幂等性
----
用 ``ADD COLUMN IF NOT EXISTS``：空库重放时 ``pg_standalone_001`` 按当时的 ORM
元数据建表可能已经带上该列，重复添加会报错。Downgrade 同样 IF EXISTS。
"""
from alembic import op

from migrations._legacy_base_guard import base_schema_absent

revision = 'pg_standalone_109_add_user_token_version'
down_revision = 'pg_standalone_108_drop_legacy_orphan_indexes'
branch_labels = None
depends_on = None


def upgrade():
    if base_schema_absent():
        return
    op.execute(
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS token_version '
        'INTEGER NOT NULL DEFAULT 0'
    )
    # ORM 声明了 comment，迁移必须同步——否则 alembic check 会报 modify_comment。
    # 对已被 001 建出该列的库，COMMENT 是幂等重设。
    op.execute('COMMENT ON COLUMN "user".token_version IS \'会话版本\'')


def downgrade():
    if base_schema_absent():
        return
    op.execute('ALTER TABLE "user" DROP COLUMN IF EXISTS token_version')
