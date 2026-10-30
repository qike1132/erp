"""
数据库迁移脚本：创建采购计划新表结构 + 修改现有表

新增表：purchase_plans, purchase_plan_details, shipment_records
修改表：customer 增加 icon_url, staging_purchase_plan 增加 plan_month
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import inspect, text

from fastapi_app.core.database import SyncSessionLocal, sync_engine


def main() -> None:
    from _prod_write_guard import require_prod_write_consent

    require_prod_write_consent('创建采购计划历史表结构（生产库 DDL）')

    session = SyncSessionLocal()

    try:
        inspector = inspect(sync_engine)
        existing_tables = inspector.get_table_names()

        # 1. 创建 purchase_plans 表
        if 'purchase_plans' not in existing_tables:
            session.execute(text("""
                CREATE TABLE purchase_plans (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    plan_no VARCHAR(32) NOT NULL UNIQUE COMMENT '计划编号',
                    plan_month VARCHAR(7) NOT NULL COMMENT '计划月份 YYYY-MM',
                    customer_id INT NOT NULL COMMENT '客户ID',
                    customer_name VARCHAR(100) NOT NULL COMMENT '客户名称',
                    status VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT '状态',
                    remark TEXT NULL COMMENT '备注',
                    upload_batch VARCHAR(64) NULL COMMENT '上传批次ID',
                    created_by VARCHAR(50) NULL COMMENT '创建人',
                    create_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                    INDEX idx_ppl_plan_month (plan_month),
                    INDEX idx_ppl_customer_id (customer_id),
                    INDEX idx_ppl_status (status),
                    INDEX idx_ppl_upload_batch (upload_batch),
                    CONSTRAINT fk_ppl_customer FOREIGN KEY (customer_id) REFERENCES customer(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='采购计划主表'
            """))
            session.commit()
            print("[OK] 创建表 purchase_plans")
        else:
            print("[SKIP] 表 purchase_plans 已存在")

        # 2. 创建 purchase_plan_details 表
        if 'purchase_plan_details' not in existing_tables:
            session.execute(text("""
                CREATE TABLE purchase_plan_details (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    plan_id INT NOT NULL COMMENT '关联主单ID',
                    product_id INT NOT NULL COMMENT '产品ID',
                    product_name VARCHAR(100) NOT NULL COMMENT '产品名称',
                    barcode VARCHAR(50) NOT NULL COMMENT '69码',
                    plan_date DATE NOT NULL COMMENT '计划日期',
                    quantity INT NOT NULL COMMENT '计划数量',
                    shipped_qty INT DEFAULT 0 COMMENT '已出货数量',
                    remark TEXT NULL COMMENT '备注',
                    INDEX idx_ppd_plan_date (plan_id, plan_date),
                    INDEX idx_ppd_product_id (product_id),
                    INDEX idx_ppd_plan_date_only (plan_date),
                    CONSTRAINT fk_ppd_plan FOREIGN KEY (plan_id) REFERENCES purchase_plans(id) ON DELETE CASCADE,
                    CONSTRAINT fk_ppd_product FOREIGN KEY (product_id) REFERENCES product(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='采购计划明细表'
            """))
            session.commit()
            print("[OK] 创建表 purchase_plan_details")
        else:
            print("[SKIP] 表 purchase_plan_details 已存在")

        # 3. 创建 shipment_records 表
        if 'shipment_records' not in existing_tables:
            session.execute(text("""
                CREATE TABLE shipment_records (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    shipment_no VARCHAR(64) NOT NULL UNIQUE COMMENT '原始出货单号',
                    customer_id INT NOT NULL COMMENT '客户ID',
                    customer_name VARCHAR(100) NOT NULL COMMENT '客户名称',
                    product_id INT NOT NULL COMMENT '产品ID',
                    product_name VARCHAR(100) NOT NULL COMMENT '产品名称',
                    quantity INT NOT NULL COMMENT '出货数量',
                    shipment_date DATE NOT NULL COMMENT '出货日期',
                    source_type VARCHAR(20) DEFAULT 'stockout' COMMENT '来源类型',
                    source_id INT NULL COMMENT '来源记录ID',
                    synced_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '同步时间',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                    INDEX idx_sr_customer_product_date (customer_id, product_id, shipment_date),
                    INDEX idx_sr_shipment_date (shipment_date)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='出货记录同步表'
            """))
            session.commit()
            print("[OK] 创建表 shipment_records")
        else:
            print("[SKIP] 表 shipment_records 已存在")

        # 4. customer 表增加 icon_url 字段
        customer_columns = [c['name'] for c in inspector.get_columns('customer')]
        if 'icon_url' not in customer_columns:
            session.execute(text("""
                ALTER TABLE customer ADD COLUMN icon_url VARCHAR(200) NULL COMMENT '客户图标URL' AFTER note
            """))
            session.commit()
            print("[OK] customer 表新增 icon_url 字段")
        else:
            print("[SKIP] customer 表 icon_url 字段已存在")

        # 5. staging_purchase_plan 表增加 plan_month 字段
        spp_columns = [c['name'] for c in inspector.get_columns('staging_purchase_plan')]
        if 'plan_month' not in spp_columns:
            session.execute(text("""
                ALTER TABLE staging_purchase_plan ADD COLUMN plan_month VARCHAR(7) NULL COMMENT '计划月份 YYYY-MM' AFTER plan_date
            """))
            session.commit()
            print("[OK] staging_purchase_plan 表新增 plan_month 字段")
        else:
            print("[SKIP] staging_purchase_plan 表 plan_month 字段已存在")

        print("\n迁移完成！")
    finally:
        session.close()


if __name__ == '__main__':
    main()
