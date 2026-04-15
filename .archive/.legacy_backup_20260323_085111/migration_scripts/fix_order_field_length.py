"""
修复Data too long错误
增加Order模型字段长度限制
"""
from app import app, db
from sqlalchemy import text


def fix_order_field_length():
    """修复Order表字段长度"""
    
    with app.app_context():
        try:
            # 检查数据库类型
            db_type = app.config.get('SQLALCHEMY_DATABASE_URI', '').split(':')[0]
            
            if 'mysql' in db_type:
                print("检测到MySQL数据库,执行ALTER TABLE...")
                
                # 增加order_no字段长度从20到50
                db.session.execute(text('ALTER TABLE `order` MODIFY COLUMN order_no VARCHAR(50) NOT NULL'))
                print("✓ order_no字段长度已增加到50")
                
                # 增加customer字段长度从100到200
                db.session.execute(text('ALTER TABLE `order` MODIFY COLUMN customer VARCHAR(200) NOT NULL'))
                print("✓ customer字段长度已增加到200")
                
                # 增加status字段长度从20到50
                db.session.execute(text('ALTER TABLE `order` MODIFY COLUMN status VARCHAR(50)'))
                print("✓ status字段长度已增加到50")
                
                db.session.commit()
                print("\n✅ 数据库字段长度修复成功!")
                
            elif 'sqlite' in db_type:
                print("检测到SQLite数据库")
                print("SQLite不支持ALTER TABLE MODIFY,需要重建表")
                print("建议: 删除数据库文件重新创建,或使用迁移工具")
                
            else:
                print(f"未知数据库类型: {db_type}")
                
        except Exception as e:
            print(f"❌ 修复失败: {e}")
            db.session.rollback()


def check_current_data():
    """检查当前数据长度"""
    from app import Order
    
    with app.app_context():
        orders = Order.query.all()
        
        print("\n=== 当前订单数据检查 ===\n")
        
        max_order_no = 0
        max_customer = 0
        max_status = 0
        
        for order in orders:
            if order.order_no:
                max_order_no = max(max_order_no, len(order.order_no))
            if order.customer:
                max_customer = max(max_customer, len(order.customer))
            if order.status:
                max_status = max(max_status, len(order.status))
        
        print(f"order_no最大长度: {max_order_no} (限制: 20)")
        print(f"customer最大长度: {max_customer} (限制: 100)")
        print(f"status最大长度: {max_status} (限制: 20)")
        
        if max_order_no > 20:
            print(f"⚠️  order_no超出限制 {max_order_no - 20} 个字符")
        if max_customer > 100:
            print(f"⚠️  customer超出限制 {max_customer - 100} 个字符")
        if max_status > 20:
            print(f"⚠️  status超出限制 {max_status - 20} 个字符")


if __name__ == '__main__':
    print("=" * 60)
    print("修复Order表Data too long错误")
    print("=" * 60)
    
    # 先检查数据
    check_current_data()
    
    # 执行修复
    print("\n" + "=" * 60)
    fix_order_field_length()
    print("=" * 60)
