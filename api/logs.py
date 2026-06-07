from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
import io
import json
import csv

from database import get_db
from database.models import TransactionType, LogAction
from utils.operation_log import OperationLogger
from schemas import OperationLogSchema, OperationLogQuery, APIResponse, PaginatedResponse
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/logs", tags=["操作日志"])
logger = get_logger("api_logs")


@router.get("", response_model=PaginatedResponse)
def query_logs(
    employee_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    transaction_type: Optional[TransactionType] = None,
    action: Optional[LogAction] = None,
    resource_type: Optional[str] = None,
    operator_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    logs = OperationLogger.query_logs(
        db=db,
        employee_id=employee_id,
        start_time=start_time,
        end_time=end_time,
        transaction_type=transaction_type,
        action=action,
        resource_type=resource_type,
        operator_id=operator_id,
        skip=skip,
        limit=limit,
    )
    total = OperationLogger.count_logs(
        db=db,
        employee_id=employee_id,
        start_time=start_time,
        end_time=end_time,
        transaction_type=transaction_type,
        action=action,
        resource_type=resource_type,
        operator_id=operator_id,
    )
    return PaginatedResponse(
        data=[OperationLogSchema.model_validate(l).model_dump() for l in logs],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/export/json")
def export_logs_json(
    employee_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    transaction_type: Optional[TransactionType] = None,
    action: Optional[LogAction] = None,
    resource_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    logs_data = OperationLogger.export_logs(
        db=db,
        employee_id=employee_id,
        start_time=start_time,
        end_time=end_time,
        transaction_type=transaction_type,
        action=action,
        resource_type=resource_type,
    )

    json_str = json.dumps(logs_data, ensure_ascii=False, indent=2, default=str)
    buf = io.BytesIO(json_str.encode("utf-8"))

    return StreamingResponse(
        buf,
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=operation_logs_{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
        },
    )


@router.get("/export/csv")
def export_logs_csv(
    employee_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    transaction_type: Optional[TransactionType] = None,
    action: Optional[LogAction] = None,
    resource_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    logs_data = OperationLogger.export_logs(
        db=db,
        employee_id=employee_id,
        start_time=start_time,
        end_time=end_time,
        transaction_type=transaction_type,
        action=action,
        resource_type=resource_type,
    )

    output = io.StringIO()
    if logs_data:
        fieldnames = list(logs_data[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(logs_data)

    output.seek(0)
    buf = io.BytesIO(output.getvalue().encode("utf-8-sig"))

    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=operation_logs_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
        },
    )


@router.post("/batch-export", response_model=APIResponse)
def batch_export_logs(query: OperationLogQuery, db: Session = Depends(get_db)):
    logs_data = OperationLogger.export_logs(
        db=db,
        employee_id=query.employee_id,
        start_time=query.start_time,
        end_time=query.end_time,
        transaction_type=query.transaction_type,
        action=query.action,
        resource_type=query.resource_type,
    )
    return APIResponse(
        data={"total_records": len(logs_data), "logs": logs_data},
        message=f"批量导出完成，共 {len(logs_data)} 条记录",
    )
