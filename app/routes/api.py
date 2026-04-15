"""
API路由蓝图
部分API已迁移至 FastAPI，此文件仅保留无FastAPI等效的路由
已迁移的路由:
  - /product-search → /api/v1/aux/product-search
  - /product-available-stock → /api/v1/aux/product-available-stock
  - /inventory-logs/<id> → /api/v1/aux/inventory-logs/{id}
  - /available-stockins → /api/v1/aux/available-stockins
  - /stockin-info/<id> → /api/v1/aux/stockin-info/{id}
  - /available-shipment → /api/v1/aux/available-shipment
  - /deduction-logs → /api/v1/reports/deduction-logs
  - DELETE /stockout/<id> → /api/v1/aux/stockout/{id}
  - DELETE /stockin/<id> → /api/v1/aux/stockin/{id}
  - DELETE /order/<id> → /api/v1/orders/delete/{id}
  - DELETE /customer/<id> → /api/v1/aux/customer/{id}
  - DELETE /product/<id> → /api/v1/products/delete/{id}
"""
from flask import Blueprint, request, jsonify, current_app, Response
from app import db, csrf
from app.models import Product, Order, StockIn, StockOut, InventoryLog
from sqlalchemy import text as sa_text
from app.utils.permission_decorators import api_permission_required
import time

api_bp = Blueprint('api', __name__, url_prefix='/api')

csrf.exempt(api_bp)

try:
    from utils.smart_cache import (
        product_cache, order_cache, stock_cache, customer_cache,
        api_response_cache, get_combined_cache_stats, cached,
        rate_limited, connection_pool
    )
    from utils.enhanced_execution import (
        resilient_retry, error_diagnoser, cost_tracker, speculative_executor
    )
    ENHANCED_CACHE = True
except ImportError:
    product_cache = None
    ENHANCED_CACHE = False


# ==================== 系统健康检查 ====================

@api_bp.route('/health')
def health_check():
    """应用级探针 (Health Check API) - 增强版"""
    try:
        db.session.execute(sa_text('SELECT 1'))
        health_data = {
            "status": "ok",
            "db": "connected",
            "timestamp": time.time(),
            "enhanced_cache": ENHANCED_CACHE
        }
        if ENHANCED_CACHE:
            cache_stats = get_combined_cache_stats()
            health_data['cache'] = {
                'hit_rate': cache_stats.get('_summary', {}).get('overall_hit_rate', 'N/A'),
                'total_entries': cache_stats.get('_summary', {}).get('total_entries', 0)
            }
        return jsonify(health_data), 200
    except Exception as e:
        current_app.logger.error(f"健康检查失败: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "db": "disconnected",
            "details": "系统检查失败，请稍后重试"
        }), 500


@api_bp.route('/metrics')
def prometheus_metrics():
    """Prometheus 指标端点（Flask 侧）

    提供 Flask 应用的基础指标。完整的请求级指标由 FastAPI 侧的
    /metrics 端点统一暴露（通过 Nginx 代理）。
    """
    try:
        from utils.flask_metrics import get_metrics, get_content_type
        content = get_metrics()
        return Response(content, mimetype=get_content_type())
    except ImportError:
        return jsonify({
            'status': 'error',
            'message': 'prometheus_client 未安装，请执行: pip install prometheus-client'
        }), 501
    except Exception as e:
        current_app.logger.error(f"指标生成失败: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': '指标生成失败'
        }), 500


@api_bp.route('/system/stats')
@api_permission_required('product_view')
def system_stats():
    """系统统计信息 (缓存命中率/成本追踪/性能数据)"""
    stats = {
        'cache': {},
        'cost': {},
        'performance': {}
    }

    if ENHANCED_CACHE:
        stats['cache'] = get_combined_cache_stats()
        stats['cost'] = cost_tracker.get_total_stats()
        from utils.performance_monitor import performance_monitor, query_tracker
        stats['performance'] = {
            **performance_monitor.get_stats(),
            'queries': query_tracker.get_stats()
        }

    return jsonify(stats)


# ==================== 批量提交API (无FastAPI等效) ====================

@api_bp.route('/batch-submit-orders', methods=['POST'])
@api_permission_required('order_manage')
def batch_submit_orders():
    """批量提交订单"""
    from utils.number_generator import generate_order_number
    from datetime import datetime
    from app.routes.batch import process_order_deduction

    try:
        data = request.get_json()
        orders_data = data.get('orders', [])

        results = []
        for order_data in orders_data:
            try:
                product_id = order_data.get('product_id')
                customer = order_data.get('customer')
                quantity = order_data.get('quantity')

                if not all([product_id, customer, quantity]):
                    results.append({
                        'success': False,
                        'error': '缺少必填字段',
                        'order_no': order_data.get('order_no', '未知')
                    })
                    continue

                product = db.session.get(Product, product_id)
                if not product:
                    results.append({
                        'success': False,
                        'error': f'产品 ID {product_id} 不存在',
                        'order_no': order_data.get('order_no', '未知')
                    })
                    continue

                deduct_stock = order_data.get('deduct_stock', False)
                deduct_quantity = int(order_data.get('deduct_quantity', order_data.get('deductible_quantity', 0)))

                order = Order(
                    order_no=generate_order_number(db, Order),
                    product_id=product_id,
                    customer=customer,
                    quantity=int(quantity),
                    order_date=datetime.now(),
                    status='待备货',
                    note=order_data.get('note', '')
                )
                db.session.add(order)
                db.session.flush()

                product.current_stock += int(quantity)

                log = InventoryLog(
                    product_id=product_id,
                    change_type='订单创建',
                    change_quantity=int(quantity),
                    change_date=datetime.now(),
                    customer=customer,
                    related_id=str(order.id),
                    note=f'订单 {order.order_no} 创建'
                )
                db.session.add(log)

                if deduct_stock and (deduct_stock == 'on' or deduct_stock is True) and deduct_quantity > 0:
                    try:
                        process_order_deduction(
                            order,
                            product_id,
                            int(quantity),
                            deduct_stock=True,
                            custom_deduct_quantity=deduct_quantity,
                            product=product
                        )
                    except Exception as ded_err:
                        current_app.logger.error(f"订单抵扣处理失败: {ded_err}", exc_info=True)
                        results.append({
                            'success': False,
                            'error': '抵扣处理失败，请稍后重试',
                            'order_no': order.order_no
                        })
                        continue

                results.append({
                    'success': True,
                    'order_no': order.order_no,
                    'id': order.id
                })
            except Exception as e:
                current_app.logger.error(f"批量订单处理单项失败: {e}", exc_info=True)
                results.append({
                    'success': False,
                    'error': '订单处理失败，请稍后重试',
                    'order_no': order_data.get('order_no', '未知')
                })

        db.session.commit()
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"批量提交订单失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': '批量提交订单失败，请稍后重试'}), 500


@api_bp.route('/batch-submit-stockins', methods=['POST'])
@api_permission_required('stockin_manage')
def batch_submit_stockins():
    """批量提交入库"""
    from utils.number_generator import generate_stockin_number
    from datetime import datetime

    try:
        data = request.get_json()
        stockins_data = data.get('stockins', [])

        results = []
        for stockin_data in stockins_data:
            try:
                product_id = stockin_data.get('product_id')
                customer = stockin_data.get('customer')
                quantity = stockin_data.get('quantity')

                if not all([product_id, customer, quantity]):
                    results.append({
                        'success': False,
                        'error': '缺少必填字段',
                        'id': stockin_data.get('id', '未知')
                    })
                    continue

                product = db.session.get(Product, product_id)
                if not product:
                    results.append({
                        'success': False,
                        'error': f'产品ID {product_id} 不存在',
                        'id': stockin_data.get('id', '未知')
                    })
                    continue

                stockin = StockIn(
                    stockin_no=generate_stockin_number(db, StockIn),
                    product_id=product_id,
                    customer=customer,
                    quantity=int(quantity),
                    stockin_date=datetime.now(),
                    note=stockin_data.get('note', '')
                )
                db.session.add(stockin)
                db.session.flush()

                product.current_stock += int(quantity)

                log = InventoryLog(
                    product_id=product_id,
                    change_type='备货入库',
                    change_quantity=int(quantity),
                    change_date=datetime.now(),
                    customer=customer,
                    related_id=str(stockin.id),
                    note=f'备货 {stockin.stockin_no} 入库'
                )
                db.session.add(log)

                results.append({
                    'success': True,
                    'stockin_no': stockin.stockin_no,
                    'id': stockin.id
                })
            except Exception as e:
                current_app.logger.error(f"批量入库处理单项失败: {e}", exc_info=True)
                results.append({
                    'success': False,
                    'error': '入库处理失败，请稍后重试',
                    'id': stockin_data.get('id', '未知')
                })

        db.session.commit()
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"批量提交入库失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': '批量提交入库失败，请稍后重试'}), 500


from app.services.stock_service import calculate_available_shipment_quantity as calculate_available_shipment_quantity_api


@api_bp.route('/batch-submit-stockouts', methods=['POST'])
@api_permission_required('stockout_manage')
def batch_submit_stockouts():
    """批量提交出库"""
    from utils.number_generator import generate_stockout_number
    from datetime import datetime
    from app.models import Order

    try:
        data = request.get_json()
        stockouts_data = data.get('stockouts', [])

        results = []
        for stockout_data in stockouts_data:
            try:
                product_id = stockout_data.get('product_id')
                quantity = stockout_data.get('quantity')
                customer = stockout_data.get('customer', '')

                if not all([product_id, quantity]):
                    results.append({
                        'success': False,
                        'error': '缺少必填字段',
                        'id': stockout_data.get('id', '未知')
                    })
                    continue

                customer = str(customer).strip()
                if not customer:
                    results.append({
                        'success': False,
                        'error': '出货必须选择客户，需要有订单支持',
                        'id': stockout_data.get('id', '未知')
                    })
                    continue

                product = db.session.get(Product, product_id)
                if not product:
                    results.append({
                        'success': False,
                        'error': f'产品ID {product_id} 不存在',
                        'id': stockout_data.get('id', '未知')
                    })
                    continue

                qty = int(quantity)
                if product.current_stock < qty:
                    results.append({
                        'success': False,
                        'error': f'库存不足，当前库存: {product.current_stock}',
                        'id': stockout_data.get('id', '未知')
                    })
                    continue

                shipment_info = calculate_available_shipment_quantity_api(product_id, customer)
                if shipment_info['available_quantity'] <= 0:
                    results.append({
                        'success': False,
                        'error': f'客户{customer}没有可用的订单支持出货',
                        'id': stockout_data.get('id', '未知')
                    })
                    continue

                if qty > shipment_info['available_quantity']:
                    results.append({
                        'success': False,
                        'error': f'出货数量{qty}超过可出货量{shipment_info["available_quantity"]}',
                        'id': stockout_data.get('id', '未知')
                    })
                    continue

                remaining_qty = qty
                for order_detail in shipment_info['orders']:
                    if remaining_qty <= 0:
                        break
                    if order_detail['available'] > 0:
                        ship_qty = min(remaining_qty, order_detail['available'])
                        stockout_no = generate_stockout_number(db, StockOut)
                        stockout = StockOut(
                            stockout_no=stockout_no,
                            product_id=product_id,
                            quantity=ship_qty,
                            stockout_date=datetime.now(),
                            customer=customer,
                            order_id=order_detail['order_id'],
                            note=stockout_data.get('note', '')
                        )
                        db.session.add(stockout)
                        db.session.flush()
                        remaining_qty -= ship_qty

                product.current_stock -= qty

                log = InventoryLog(
                    product_id=product_id,
                    change_type='出货',
                    change_quantity=-qty,
                    change_date=datetime.now(),
                    customer=customer,
                    related_id='',
                    note=f'出货：客户{customer}，数量{qty}'
                )
                db.session.add(log)

                results.append({
                    'success': True,
                    'stockout_no': stockout.stockout_no if 'stockout' in locals() else '',
                    'id': stockout.id if 'stockout' in locals() else None
                })
            except Exception as e:
                current_app.logger.error(f"批量出库处理单项失败: {e}", exc_info=True)
                results.append({
                    'success': False,
                    'error': '出库处理失败，请稍后重试',
                    'id': stockout_data.get('id', '未知')
                })

        db.session.commit()
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"批量提交出库失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': '批量提交出库失败，请稍后重试'}), 500


# ==================== 其他API (无FastAPI等效) ====================

@api_bp.route('/log-operation', methods=['POST'])
def log_operation():
    """记录操作日志"""
    try:
        data = request.get_json()
        # TODO: 实现操作日志记录
        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"操作日志记录失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': '操作日志记录失败，请稍后重试'}), 500
