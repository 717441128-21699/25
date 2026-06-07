from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from decimal import Decimal

from database import get_db
from services import ExecutiveMonitoringService, ShareholderService
from schemas import ExecutiveAlertSchema, APIResponse, PaginatedResponse
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/executive-alerts", tags=["高管监控"])
logger = get_logger("api_exec_alert")


@router.get("/monitor", response_model=APIResponse)
def monitor_all_executives(db: Session = Depends(get_db)):
    try:
        alerts = ExecutiveMonitoringService.monitor_all_executives(db)
        return APIResponse(data={"count": len(alerts), "alerts": alerts})
    except Exception as e:
        logger.error(f"高管监控失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pending", response_model=PaginatedResponse)
def list_pending_alerts(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    alerts = ExecutiveMonitoringService.list_pending_alerts(db, skip, limit)
    return PaginatedResponse(
        data=[ExecutiveAlertSchema.model_validate(a).model_dump() for a in alerts],
        total=len(alerts),
        skip=skip,
        limit=limit,
    )


@router.post("/check", response_model=APIResponse)
def check_executive_reduction(
    employee_id: str,
    shares_before: int,
    shares_after: int,
    db: Session = Depends(get_db),
):
    try:
        result = ExecutiveMonitoringService.check_executive_reduction(
            db, employee_id, shares_before, shares_after
        )

        if result.get("triggered") and result.get("alerts"):
            for alert_info in result["alerts"]:
                ExecutiveMonitoringService.create_alert(
                    db=db,
                    employee_id=employee_id,
                    shares_before=shares_before,
                    shares_reduced=shares_before - shares_after,
                    shares_after=shares_after,
                    alert_type=alert_info["type"],
                    threshold_value=Decimal(alert_info["threshold"]) / 100,
                    actual_value=Decimal(result["percentage"]) / 100,
                )

        return APIResponse(data=result)
    except Exception as e:
        logger.error(f"检查高管减持失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{alert_id}/approve", response_model=APIResponse)
def approve_alert(
    alert_id: str,
    approver_id: str = "compliance",
    approver_name: str = "合规管理员",
    db: Session = Depends(get_db),
):
    try:
        alert = ExecutiveMonitoringService.approve_alert(
            db, alert_id, approver_id, approver_name
        )
        return APIResponse(
            data=ExecutiveAlertSchema.model_validate(alert).model_dump(),
            message="公告草稿已通过合规审核",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/shareholders", response_model=APIResponse)
def get_executive_shareholders(db: Session = Depends(get_db)):
    shareholders = ShareholderService.get_executive_shareholders(db)
    return APIResponse(data=shareholders)
