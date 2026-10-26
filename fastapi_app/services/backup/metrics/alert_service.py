"""
备份告警服务

提供备份失败自动告警功能，支持多种告警方式：
1. 日志记录错误级别
2. 邮件通知（如果配置了邮件）
3. 写入错误统计到数据库
4. 触发Webhook（如果配置了）
5. 重试机制和指数退避
6. 连续失败阈值告警升级
"""

import asyncio
import html
import json
import logging
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class BackupAlertService:
    """备份告警服务类"""

    def __init__(self):
        self.alert_config = self._load_alert_config()
        self.failure_counts = {}  # 任务失败计数缓存
        self.last_alert_times = {}  # 最近告警时间缓存

    def _load_alert_config(self) -> dict[str, Any]:
        """加载告警配置"""
        import os

        return {
            # 邮件配置
            'email_enabled': os.environ.get('BACKUP_ALERT_EMAIL_ENABLED', 'false').lower() == 'true',
            'smtp_host': os.environ.get('BACKUP_ALERT_SMTP_HOST', 'smtp.gmail.com'),
            'smtp_port': int(os.environ.get('BACKUP_ALERT_SMTP_PORT', '587')),
            'smtp_username': os.environ.get('BACKUP_ALERT_SMTP_USERNAME', ''),
            'smtp_password': os.environ.get('BACKUP_ALERT_SMTP_PASSWORD', ''),
            'email_from': os.environ.get('BACKUP_ALERT_EMAIL_FROM', ''),
            'email_to': os.environ.get('BACKUP_ALERT_EMAIL_TO', '').split(','),
            'email_subject_prefix': os.environ.get('BACKUP_ALERT_EMAIL_SUBJECT_PREFIX', '[ERP Backup Alert]'),

            # Webhook配置
            'webhook_enabled': os.environ.get('BACKUP_ALERT_WEBHOOK_ENABLED', 'false').lower() == 'true',
            'webhook_url': os.environ.get('BACKUP_ALERT_WEBHOOK_URL', ''),
            'webhook_headers': os.environ.get('BACKUP_ALERT_WEBHOOK_HEADERS', '{}'),

            # 告警阈值
            'failure_threshold': int(os.environ.get('BACKUP_ALERT_FAILURE_THRESHOLD', '3')),
            'alert_cooldown_minutes': int(os.environ.get('BACKUP_ALERT_COOLDOWN_MINUTES', '30')),
            'critical_threshold': int(os.environ.get('BACKUP_ALERT_CRITICAL_THRESHOLD', '5')),

            # 重试配置
            'max_retries': int(os.environ.get('BACKUP_ALERT_MAX_RETRIES', '3')),
            'retry_delay_base': int(os.environ.get('BACKUP_ALERT_RETRY_DELAY_BASE', '2')),
        }

    async def send_alert(self,
                        task_name: str,
                        error: str,
                        task_type: str = 'backup',
                        severity: str = 'error',
                        additional_info: dict[str, Any] | None = None) -> bool:
        """
        发送备份告警

        Args:
            task_name: 任务名称
            error: 错误信息
            task_type: 任务类型（backup/restore/cleanup/health_check）
            severity: 严重级别（info/warning/error/critical）
            additional_info: 附加信息

        Returns:
            bool: 是否发送成功
        """
        try:
            # 更新失败计数
            self._update_failure_count(task_name, severity)

            # 准备告警数据
            alert_data = self._prepare_alert_data(task_name, error, task_type, severity, additional_info)

            # Z05-R21：不再把告警按任务名 LIKE 关联到 BackupRecord —— 任务名不是
            # 文件名子串，常态 no-op；碰巧命中时还会误改最近一条无关记录的状态。
            # 专用告警表落地前只走日志/通知通道。
            # 发送告警
            success = True

            # 1. 日志记录
            self._log_alert(alert_data)

            # 通知渠道（邮件/Webhook）受失败阈值与冷却时间控制
            notify = self._should_send_alert(task_name, severity)

            # M3（2026-10-26）：冷却只应在「真的投递出去了」之后生效。
            # 原先只要 notify=True 就进入冷却 —— 两个渠道都没启用、或投递失败时，
            # 下一条真实告警会被自己的冷却窗口吞掉（告警系统对故障失明）。
            attempted = False

            # 2. 邮件通知
            if self.alert_config['email_enabled'] and notify:
                attempted = True
                email_success = await self._send_email_alert(alert_data)
                success = success and email_success

            # 3. Webhook通知
            if self.alert_config['webhook_enabled'] and notify:
                attempted = True
                webhook_success = await self._send_webhook_alert(alert_data)
                success = success and webhook_success

            # 4. 更新最近告警时间（仅在真正投递成功后进入冷却期）
            if notify:
                if not attempted:
                    logger.warning(
                        '告警无可用通知渠道（邮件/Webhook 均未启用），仅落日志，'
                        '不进入冷却期: %s', task_name,
                    )
                elif success:
                    self.last_alert_times[task_name] = datetime.now()
                else:
                    logger.warning(
                        '告警投递失败，不进入冷却期以便下轮重试: %s', task_name,
                    )

            logger.info(f"告警发送完成: {task_name}, 严重级别: {severity}")
            return success

        except Exception as e:  # defensive: alert sender must never propagate exceptions
            logger.error(f"发送告警时发生错误: {e}")
            return False

    def _update_failure_count(self, task_name: str, severity: str):
        """更新失败计数"""
        if task_name not in self.failure_counts:
            self.failure_counts[task_name] = {
                'error': 0,
                'critical': 0,
                'last_failure_time': None
            }

        if severity == 'critical':
            self.failure_counts[task_name]['critical'] += 1
        elif severity in ['error', 'warning']:
            self.failure_counts[task_name]['error'] += 1

        self.failure_counts[task_name]['last_failure_time'] = datetime.now()

        # 检查是否需要升级告警级别
        error_count = self.failure_counts[task_name]['error']
        self.failure_counts[task_name]['critical']

        if error_count >= self.alert_config['critical_threshold']:
            logger.warning(f"任务 {task_name} 连续失败 {error_count} 次，建议升级告警级别")

    def _should_send_alert(self, task_name: str, severity: str) -> bool:
        """检查是否需要发送告警"""
        # 如果是critical级别，总是发送
        if severity == 'critical':
            return True

        # 检查冷却时间
        if task_name in self.last_alert_times:
            last_alert = self.last_alert_times[task_name]
            cooldown_minutes = self.alert_config['alert_cooldown_minutes']
            if datetime.now() - last_alert < timedelta(minutes=cooldown_minutes):
                return False

        # 检查失败阈值
        if task_name in self.failure_counts:
            error_count = self.failure_counts[task_name]['error']
            if error_count < self.alert_config['failure_threshold']:
                return False

        return True

    def _prepare_alert_data(self,
                           task_name: str,
                           error: str,
                           task_type: str,
                           severity: str,
                           additional_info: dict[str, Any] | None) -> dict[str, Any]:
        """准备告警数据"""
        failure_counts = self.failure_counts.get(task_name, {})
        last_failure_time = failure_counts.get('last_failure_time')
        alert_data = {
            'task_name': task_name,
            'error': error,
            'task_type': task_type,
            'severity': severity,
            'timestamp': datetime.now().isoformat(),
            'hostname': self._get_hostname(),
            'failure_counts': {
                'error': failure_counts.get('error', 0),
                'critical': failure_counts.get('critical', 0),
                'last_failure_time': last_failure_time.isoformat() if last_failure_time else None,
            },
        }

        if additional_info:
            alert_data.update(additional_info)

        return alert_data

    def _log_alert(self, alert_data: dict[str, Any]) -> None:
        """记录日志告警"""
        log_message = (
            f"备份告警 - 任务: {alert_data['task_name']}, "
            f"类型: {alert_data['task_type']}, "
            f"严重级别: {alert_data['severity']}, "
            f"错误: {alert_data['error']}"
        )

        if alert_data['severity'] == 'critical':
            logger.critical(log_message)
        elif alert_data['severity'] == 'error':
            logger.error(log_message)
        elif alert_data['severity'] == 'warning':
            logger.warning(log_message)
        else:
            logger.info(log_message)

    async def _send_email_alert(self, alert_data: dict[str, Any]) -> bool:
        """发送邮件告警"""
        try:
            if not self.alert_config['email_from'] or not self.alert_config['email_to']:
                logger.warning("邮件告警配置不完整，跳过发送")
                return False

            # 创建邮件
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"{self.alert_config['email_subject_prefix']} {alert_data['severity'].upper()}: {alert_data['task_name']}"
            msg['From'] = self.alert_config['email_from']
            msg['To'] = ', '.join(self.alert_config['email_to'])

            # 纯文本内容
            text_content = self._generate_email_text(alert_data)
            text_part = MIMEText(text_content, 'plain', 'utf-8')
            msg.attach(text_part)

            # HTML内容
            html_content = self._generate_email_html(alert_data)
            html_part = MIMEText(html_content, 'html', 'utf-8')
            msg.attach(html_part)

            # 发送邮件
            with smtplib.SMTP(self.alert_config['smtp_host'], self.alert_config['smtp_port']) as server:
                server.starttls()
                server.login(self.alert_config['smtp_username'], self.alert_config['smtp_password'])
                server.send_message(msg)

            logger.info(f"邮件告警发送成功: {alert_data['task_name']}")
            return True

        except (OSError, smtplib.SMTPException) as e:
            logger.error(f"发送邮件告警失败: {e}")
            return False

    def _generate_email_text(self, alert_data: dict[str, Any]) -> str:
        """生成邮件纯文本内容"""
        text = f"""
备份告警通知

任务名称: {alert_data['task_name']}
任务类型: {alert_data['task_type']}
严重级别: {alert_data['severity'].upper()}
发生时间: {alert_data['timestamp']}
主机名称: {alert_data['hostname']}

错误信息:
{alert_data['error']}

失败统计:
- 错误次数: {alert_data['failure_counts'].get('error', 0)}
- 严重错误次数: {alert_data['failure_counts'].get('critical', 0)}
- 最后失败时间: {alert_data['failure_counts'].get('last_failure_time', 'N/A')}

请及时处理。
"""
        return text

    def _generate_email_html(self, alert_data: dict[str, Any]) -> str:
        """生成邮件HTML内容（所有动态字段均经 html.escape 转义，防止 XSS）。"""
        _e = html.escape
        severity_color = {
            'critical': '#dc3545',
            'error': '#fd7e14',
            'warning': '#ffc107',
            'info': '#17a2b8'
        }.get(str(alert_data.get('severity', '')), '#6c757d')

        task_name = _e(str(alert_data.get('task_name', '')))
        task_type = _e(str(alert_data.get('task_type', '')))
        severity = _e(str(alert_data.get('severity', '')).upper())
        timestamp = _e(str(alert_data.get('timestamp', '')))
        hostname = _e(str(alert_data.get('hostname', '')))
        error_text = _e(str(alert_data.get('error', '')))
        failure_counts = alert_data.get('failure_counts', {})
        error_count = _e(str(failure_counts.get('error', 0)))
        critical_count = _e(str(failure_counts.get('critical', 0)))
        last_failure_time = _e(str(failure_counts.get('last_failure_time', 'N/A')))

        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: {severity_color}; color: white; padding: 15px; border-radius: 5px 5px 0 0; }}
        .content {{ background-color: #f8f9fa; padding: 20px; border: 1px solid #dee2e6; border-top: none; border-radius: 0 0 5px 5px; }}
        .alert-title {{ font-size: 24px; margin: 0; }}
        .info-row {{ margin-bottom: 10px; }}
        .label {{ font-weight: bold; color: #495057; }}
        .error-box {{ background-color: #fff3cd; border: 1px solid #ffeaa7; border-radius: 4px; padding: 15px; margin: 15px 0; }}
        .stats {{ background-color: #e9ecef; padding: 10px; border-radius: 4px; margin: 15px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 class="alert-title">🔔 备份告警通知</h1>
        </div>
        <div class="content">
            <div class="info-row">
                <span class="label">任务名称:</span> {task_name}
            </div>
            <div class="info-row">
                <span class="label">任务类型:</span> {task_type}
            </div>
            <div class="info-row">
                <span class="label">严重级别:</span> <span style="color: {severity_color}; font-weight: bold;">{severity}</span>
            </div>
            <div class="info-row">
                <span class="label">发生时间:</span> {timestamp}
            </div>
            <div class="info-row">
                <span class="label">主机名称:</span> {hostname}
            </div>

            <div class="error-box">
                <h3>错误信息</h3>
                <pre style="white-space: pre-wrap; word-wrap: break-word;">{error_text}</pre>
            </div>

            <div class="stats">
                <h3>失败统计</h3>
                <div class="info-row">
                    <span class="label">错误次数:</span> {error_count}
                </div>
                <div class="info-row">
                    <span class="label">严重错误次数:</span> {critical_count}
                </div>
                <div class="info-row">
                    <span class="label">最后失败时间:</span> {last_failure_time}
                </div>
            </div>

            <p style="color: #6c757d; font-size: 14px; margin-top: 20px;">
                请及时登录系统处理此告警。
            </p>
        </div>
    </div>
</body>
</html>
"""
        return html_content

    async def _send_webhook_alert(self, alert_data: dict[str, Any]) -> bool:
        """发送Webhook告警"""
        try:
            if not self.alert_config['webhook_url']:
                logger.warning("Webhook URL未配置，跳过发送")
                return False

            headers = {}
            try:
                headers = json.loads(self.alert_config['webhook_headers'])
                if not isinstance(headers, dict):
                    headers = {}
            except (json.JSONDecodeError, TypeError):
                headers = {'Content-Type': 'application/json'}

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.alert_config['webhook_url'],
                    json=alert_data,
                    headers=headers,
                    timeout=30.0
                )

                if response.status_code >= 200 and response.status_code < 300:
                    logger.info(f"Webhook告警发送成功: {alert_data['task_name']}")
                    return True
                else:
                    # M4（2026-10-26）：不再回显响应正文。Webhook 接收端常在错误体里
                    # 回显请求内容/令牌，原文进日志等于把告警载荷与凭据复制到
                    # logs/（可被更低权限角色读取）。状态码 + 长度足够定位。
                    logger.error(
                        "Webhook告警发送失败: status=%s body_len=%s",
                        response.status_code,
                        len(response.text or ''),
                    )
                    return False

        except httpx.RequestError as e:
            logger.error(f"发送Webhook告警失败: {e}")
            return False

    def _get_hostname(self) -> str:
        """获取主机名"""
        import socket
        try:
            return socket.gethostname()
        except OSError:
            return 'unknown'

    async def retry_with_backoff(self,
                                task_func,
                                *args,
                                task_name: str = 'unknown',
                                **kwargs) -> tuple[bool, Any]:
        """
        指数退避重试机制

        Args:
            task_func: 要重试的函数
            *args: 函数参数
            task_name: 任务名称
            **kwargs: 函数关键字参数

        Returns:
            Tuple[bool, Any]: (是否成功, 结果或错误信息)
        """
        max_retries = self.alert_config['max_retries']
        base_delay = self.alert_config['retry_delay_base']

        last_error = None
        for attempt in range(max_retries + 1):  # +1 for initial attempt
            try:
                if attempt > 0:
                    delay = base_delay ** attempt  # 指数退避
                    logger.info(f"第 {attempt} 次重试 {task_name}, 等待 {delay} 秒...")
                    await asyncio.sleep(delay)

                result = await task_func(*args, **kwargs)
                logger.info(f"任务 {task_name} 第 {attempt} 次尝试成功")
                return True, result

            except Exception as e:  # defensive: retry loop must catch any task failure
                last_error = e
                logger.warning(f"任务 {task_name} 第 {attempt} 次尝试失败: {e}")

                # 发送警告级别告警（非错误级别）
                if attempt < max_retries:
                    await self.send_alert(
                        task_name=task_name,
                        error=f"第 {attempt + 1} 次尝试失败: {e!s}",
                        task_type='retry',
                        severity='warning',
                        additional_info={'attempt': attempt + 1, 'max_retries': max_retries}
                    )

        # 所有重试都失败
        logger.error(f"任务 {task_name} 所有 {max_retries} 次重试均失败")
        return False, last_error


# 全局告警服务实例
alert_service = BackupAlertService()
