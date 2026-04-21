"""
数据迁移验证脚本
整改: PostgreSQL 迁移后数据一致性验证
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


class MigrationVerifier:
    """迁移验证器"""
    
    def __init__(self, mysql_url: str, pg_url: str):
        self.mysql_engine = create_async_engine(mysql_url, pool_size=5)
        self.pg_engine = create_async_engine(pg_url, pool_size=5)
    
    async def verify_row_counts(self, tables: list) -> dict:
        """验证行数一致性"""
        results = {}
        
        for table in tables:
            try:
                async with self.mysql_engine.connect() as mysql_conn:
                    mysql_result = await mysql_conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    mysql_count = mysql_result.scalar()
                
                async with self.pg_engine.connect() as pg_conn:
                    pg_result = await pg_conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    pg_count = pg_result.scalar()
                
                match = mysql_count == pg_count
                results[table] = {
                    "mysql": mysql_count,
                    "pg": pg_count,
                    "match": match
                }
                
                if match:
                    logger.info(f"[OK] {table}: {mysql_count} rows")
                else:
                    logger.error(f"[FAIL] {table}: MySQL={mysql_count}, PG={pg_count}")
                    
            except Exception as e:
                logger.error(f"[ERROR] {table}: {e}")
                results[table] = {"error": str(e)}
        
        return results
    
    async def verify_sample_data(self, table: str, columns: list, sample_size: int = 1000) -> dict:
        """随机抽样数据比对"""
        try:
            # MySQL 随机抽样
            async with self.mysql_engine.connect() as mysql_conn:
                mysql_result = await mysql_conn.execute(
                    text(f"SELECT {','.join(columns)} FROM {table} ORDER BY RAND() LIMIT {sample_size}")
                )
                mysql_rows = [dict(row._mapping) for row in mysql_result.fetchall()]
            
            # PostgreSQL 随机抽样
            async with self.pg_engine.connect() as pg_conn:
                pg_result = await pg_conn.execute(
                    text(f"SELECT {','.join(columns)} FROM {table} ORDER BY RANDOM() LIMIT {sample_size}")
                )
                pg_rows = [dict(row._mapping) for row in pg_result.fetchall()]
            
            # 比对（按主键匹配）
            differences = []
            mysql_dict = {row.get('id', i): row for i, row in enumerate(mysql_rows)}
            pg_dict = {row.get('id', i): row for i, row in enumerate(pg_rows)}
            
            for key in set(mysql_dict.keys()) & set(pg_dict.keys()):
                if mysql_dict[key] != pg_dict[key]:
                    differences.append({
                        "id": key,
                        "mysql": mysql_dict[key],
                        "pg": pg_dict[key]
                    })
            
            match_rate = 1 - len(differences) / len(mysql_rows) if mysql_rows else 0
            
            return {
                "table": table,
                "sample_size": len(mysql_rows),
                "differences": len(differences),
                "match_rate": match_rate,
                "details": differences[:10]  # 只显示前 10 条差异
            }
            
        except Exception as e:
            logger.error(f"抽样验证失败 {table}: {e}")
            return {"error": str(e)}
    
    async def verify_checksum(self, table: str) -> dict:
        """校验和验证"""
        try:
            # MySQL CHECKSUM
            async with self.mysql_engine.connect() as mysql_conn:
                mysql_result = await mysql_conn.execute(text(f"CHECKSUM TABLE {table}"))
                mysql_checksum = mysql_result.fetchone()[1]
            
            # PostgreSQL MD5（近似）
            async with self.pg_engine.connect() as pg_conn:
                pg_result = await pg_conn.execute(
                    text(f"SELECT MD5(string_agg(row_to_json(t)::text, ',' ORDER BY id)) FROM {table} t")
                )
                pg_checksum = pg_result.scalar()
            
            return {
                "table": table,
                "mysql_checksum": mysql_checksum,
                "pg_checksum": pg_checksum,
                "match": mysql_checksum == pg_checksum
            }
            
        except Exception as e:
            logger.error(f"校验和验证失败 {table}: {e}")
            return {"error": str(e)}
    
    async def generate_report(self, tables: list) -> dict:
        """生成完整验证报告"""
        logger.info("开始生成迁移验证报告...")
        
        # 行数验证
        row_counts = await self.verify_row_counts(tables)
        
        # 抽样验证（前 3 张表）
        sample_verifications = []
        for table in tables[:3]:
            result = await self.verify_sample_data(table, ["*"])
            sample_verifications.append(result)
        
        # 汇总
        total_tables = len(tables)
        matched_tables = sum(1 for r in row_counts.values() if r.get("match", False))
        
        report = {
            "summary": {
                "total_tables": total_tables,
                "matched_tables": matched_tables,
                "failed_tables": total_tables - matched_tables,
                "status": "PASS" if matched_tables == total_tables else "FAIL"
            },
            "row_counts": row_counts,
            "sample_verifications": sample_verifications
        }
        
        logger.info(f"验证完成: {matched_tables}/{total_tables} 张表通过")
        return report
    
    async def close(self):
        """关闭连接"""
        await self.mysql_engine.dispose()
        await self.pg_engine.dispose()


async def main():
    """主函数"""
    verifier = MigrationVerifier(
        mysql_url="mysql+aiomysql://erp_app:password@localhost:3306/erp_system",
        pg_url="postgresql+asyncpg://erp_app:password@localhost:5432/erp_system"
    )
    
    try:
        tables = [
            "users", "roles", "permissions", "products", "orders",
            "order_items", "customers", "suppliers", "stock_ins",
            "stock_outs", "approvals", "notifications", "audit_logs"
        ]
        
        report = await verifier.generate_report(tables)
        
        # 保存报告
        import json
        with open("migration_verification_report.json", "w") as f:
            json.dump(report, f, indent=2, default=str)
        
        logger.info("验证报告已保存: migration_verification_report.json")
        
    finally:
        await verifier.close()


if __name__ == "__main__":
    asyncio.run(main())
