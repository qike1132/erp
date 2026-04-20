"""客户管理服务层"""
import logging
from sqlalchemy import select, func

from fastapi_app.shared_models import Customer, Order, StockIn, StockOut
from fastapi_app.services import escape_like

logger = logging.getLogger(__name__)


async def get_customers(db, status: str | None = None) -> list[Customer]:
    """获取客户列表"""
    query = select(Customer)
    if status == 'active':
        query = query.where(Customer.status == True)
    elif status == 'inactive':
        query = query.where(Customer.status == False)
    query = query.order_by(Customer.name)
    result = await db.execute(query)
    return list(result.scalars().all())


async def search_customers(db, query_str: str) -> list[Customer]:
    """搜索客户"""
    result = await db.execute(
        select(Customer).where(
            Customer.status == True,
            (Customer.name.like(f'%{escape_like(query_str)}%')) |
            (Customer.contact.like(f'%{escape_like(query_str)}%')) |
            (Customer.phone.like(f'%{escape_like(query_str)}%'))
        ).limit(20)
    )
    return list(result.scalars().all())


async def get_active_customer_names(db) -> list[dict]:
    """获取所有启用客户名称列表"""
    result = await db.execute(
        select(Customer).where(Customer.status == True).order_by(Customer.name)
    )
    return [{'id': c.id, 'name': c.name} for c in result.scalars().all()]


async def create_customer(db, name: str, contact: str | None, phone: str | None,
                          address: str | None, note: str | None) -> Customer:
    """创建客户"""
    # 检查名称唯一性
    result = await db.execute(select(Customer).where(Customer.name == name))
    if result.scalar_one_or_none():
        raise ValueError("客户名称已存在")

    customer = Customer(name=name, contact=contact, phone=phone, address=address, note=note, status=True)
    db.add(customer)
    await db.flush()
    await db.refresh(customer)
    return customer


async def update_customer(db, customer_id: int, name: str | None, contact: str | None,
                          phone: str | None, address: str | None, note: str | None,
                          status: bool | None) -> Customer:
    """更新客户"""
    customer = await db.get(Customer, customer_id)
    if not customer:
        raise ValueError("客户不存在")

    if name is not None:
        # 检查名称唯一性（排除自身）
        result = await db.execute(
            select(Customer).where(Customer.name == name, Customer.id != customer_id)
        )
        if result.scalar_one_or_none():
            raise ValueError("客户名称已存在")
        customer.name = name

    if contact is not None:
        customer.contact = contact
    if phone is not None:
        customer.phone = phone
    if address is not None:
        customer.address = address
    if note is not None:
        customer.note = note
    if status is not None:
        customer.status = status

    await db.flush()
    await db.refresh(customer)
    return customer


async def toggle_customer_status(db, customer_id: int) -> Customer:
    """切换客户状态"""
    customer = await db.get(Customer, customer_id)
    if not customer:
        raise ValueError("客户不存在")

    customer.status = not customer.status
    await db.flush()
    await db.refresh(customer)
    return customer


async def delete_customer(db, customer_id: int) -> None:
    """删除客户"""
    customer = await db.get(Customer, customer_id)
    if not customer:
        raise ValueError("客户不存在")

    # 检查关联单据
    has_orders = await db.execute(
        select(Order).where(Order.customer == customer.name).limit(1)
    )
    has_stockins = await db.execute(
        select(StockIn).where(StockIn.customer == customer.name).limit(1)
    )
    has_stockouts = await db.execute(
        select(StockOut).where(StockOut.customer == customer.name).limit(1)
    )

    if has_orders.scalar_one_or_none() or has_stockins.scalar_one_or_none() or has_stockouts.scalar_one_or_none():
        raise ValueError("该客户已有相关单据，无法删除！建议禁用该客户。")

    await db.delete(customer)
    await db.flush()
