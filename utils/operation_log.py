from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from database.models import OperationLog, LogAction, TransactionType
from utils.common import generate_id


class OperationLogger:
    @staticmethod
    def log(
        db: Session,
        action: LogAction,
        resource_type: str,
        resource_id: Optional[str] = None,
        operator_id: Optional[str] = None,
        operator_name: Optional[str] = None,
        operator_role: Optional[str] = None,
        transaction_type: Optional[TransactionType] = None,
        employee_id: Optional[str] = None,
        old_value: Optional[Dict[str, Any]] = None,
        new_value: Optional[Dict[str, Any]] = None,
        changed_fields: Optional[List[str]] = None,
        description: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> OperationLog:
        log = OperationLog(
            log_id=generate_id("LOG"),
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            operator_id=operator_id,
            operator_name=operator_name,
            operator_role=operator_role,
            transaction_type=transaction_type,
            employee_id=employee_id,
            ip_address=ip_address,
            user_agent=user_agent,
            old_value=old_value,
            new_value=new_value,
            changed_fields=changed_fields,
            description=description,
            extra_metadata=metadata,
        )
        db.add(log)
        db.flush()
        return log

    @staticmethod
    def query_logs(
        db: Session,
        employee_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        transaction_type: Optional[TransactionType] = None,
        action: Optional[LogAction] = None,
        resource_type: Optional[str] = None,
        operator_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[OperationLog]:
        query = db.query(OperationLog)

        if employee_id:
            query = query.filter(OperationLog.employee_id == employee_id)
        if start_time:
            query = query.filter(OperationLog.created_at >= start_time)
        if end_time:
            query = query.filter(OperationLog.created_at <= end_time)
        if transaction_type:
            query = query.filter(OperationLog.transaction_type == transaction_type)
        if action:
            query = query.filter(OperationLog.action == action)
        if resource_type:
            query = query.filter(OperationLog.resource_type == resource_type)
        if operator_id:
            query = query.filter(OperationLog.operator_id == operator_id)

        return (
            query.order_by(OperationLog.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    @staticmethod
    def count_logs(
        db: Session,
        employee_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        transaction_type: Optional[TransactionType] = None,
        action: Optional[LogAction] = None,
        resource_type: Optional[str] = None,
        operator_id: Optional[str] = None,
    ) -> int:
        query = db.query(OperationLog)

        if employee_id:
            query = query.filter(OperationLog.employee_id == employee_id)
        if start_time:
            query = query.filter(OperationLog.created_at >= start_time)
        if end_time:
            query = query.filter(OperationLog.created_at <= end_time)
        if transaction_type:
            query = query.filter(OperationLog.transaction_type == transaction_type)
        if action:
            query = query.filter(OperationLog.action == action)
        if resource_type:
            query = query.filter(OperationLog.resource_type == resource_type)
        if operator_id:
            query = query.filter(OperationLog.operator_id == operator_id)

        return query.count()

    @staticmethod
    def export_logs(
        db: Session,
        employee_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        transaction_type: Optional[TransactionType] = None,
        action: Optional[LogAction] = None,
        resource_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        logs = OperationLogger.query_logs(
            db=db,
            employee_id=employee_id,
            start_time=start_time,
            end_time=end_time,
            transaction_type=transaction_type,
            action=action,
            resource_type=resource_type,
            skip=0,
            limit=100000,
        )
        return [
            {
                "log_id": log.log_id,
                "created_at": log.created_at.isoformat() if log.created_at else None,
                "action": log.action.value if log.action else None,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "operator_id": log.operator_id,
                "operator_name": log.operator_name,
                "operator_role": log.operator_role,
                "transaction_type": log.transaction_type.value if log.transaction_type else None,
                "employee_id": log.employee_id,
                "description": log.description,
                "ip_address": log.ip_address,
                "old_value": log.old_value,
                "new_value": log.new_value,
                "changed_fields": log.changed_fields,
            }
            for log in logs
        ]
