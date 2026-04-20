"""
采购中心 - 修改历史 & 保存查询 & 状态日志

从 purchase_center_service.py 拆分。
"""
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from fastapi_app.shared_models import ModificationLog, SavedQuery, OrderStatusLog
from fastapi_app.services import escape_like

logger = logging.getLogger(__name__)


def get_modification_logs(db: Session, *, target_type: str = '', target_id: int = 0,
                          page: int = 1, per_page: int = 20) -> dict:
    query = db.query(ModificationLog)
    if target_type:
        query = query.filter(ModificationLog.target_type == target_type)
    if target_id:
        query = query.filter(ModificationLog.target_id == target_id)
    query = query.order_by(ModificationLog.modify_time.desc())
    total = query.count()
    logs = query.offset((page - 1) * per_page).limit(per_page).all()
    return {
        'logs': [log.to_dict() for log in logs],
        'total': total,
    }


def get_saved_queries(db: Session, query_type: str = 'purchase_order', user_id: int = 1) -> list:
    queries = db.query(SavedQuery).filter_by(
        query_type=query_type, creator_id=user_id,
    ).order_by(SavedQuery.create_time.desc()).all()
    return [q.to_dict() for q in queries]


def save_query(db: Session, data: dict, user_id: int, username: str) -> dict:
    sq = SavedQuery(
        name=data['name'],
        query_type=data.get('query_type', 'purchase_order'),
        conditions=json.dumps(data['conditions'], ensure_ascii=False),
        creator_id=user_id,
        creator_name=username,
    )
    db.add(sq)
    db.commit()
    return sq.to_dict()


def delete_saved_query(db: Session, query_id: int) -> Optional[str]:
    sq = db.get(SavedQuery, query_id)
    if not sq:
        return None
    db.delete(sq)
    db.commit()
    return '已删除'


def use_saved_query(db: Session, query_id: int) -> Optional[dict]:
    sq = db.get(SavedQuery, query_id)
    if not sq:
        return None
    sq.use_count += 1
    sq.last_use_time = datetime.now()
    db.commit()
    return sq.to_dict()


def get_status_logs(db: Session, *, target_type: str = '', target_id: int = 0,
                    order_no: str = '', page: int = 1, per_page: int = 20) -> dict:
    query = db.query(OrderStatusLog)
    if target_type:
        query = query.filter(OrderStatusLog.target_type == target_type)
    if target_id:
        query = query.filter(OrderStatusLog.target_id == target_id)
    if order_no:
        query = query.filter(OrderStatusLog.order_no.ilike(f'%{escape_like(order_no)}%'))
    query = query.order_by(OrderStatusLog.action_time.desc())
    total = query.count()
    logs = query.offset((page - 1) * per_page).limit(per_page).all()
    return {
        'logs': [log.to_dict() for log in logs],
        'total': total,
    }
