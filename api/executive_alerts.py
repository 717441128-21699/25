from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List

from database import get_db
from database.models import ExecutiveAlert, Employee
from services import ExecutiveAlertService
from schemas import (
    ExecutiveAlertSchema, APIResponse, PaginatedResponse,
)
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/executive-alerts", tags=["高管减持预警"])
logger = get_logger("api_executive_alert")


@router.post("/scan", response_model=APIResponse)
@router.post("", response_model=APIResponse)
def scan_executive_alerts(
    employee_id: Optional[str] = Query(None, description="指定高管ID扫描"),
    db: Session = Depends(get_db),
):
    try:
        if employee_id:
            employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
            if not employee:
                raise HTTPException(status_code=404, detail=f"高管不存在: {employee_id}")
            if not employee.is_executive:
                employee.is_executive = True
                db.commit()
                db.refresh(employee)
            alerts = [ExecutiveAlertService.check_holding_limits(db, employee)]
            alerts = [a for a in alerts if a]
            if not alerts:
                alerts = ExecutiveAlertService.scan_executives(db)
        else:
            alerts = ExecutiveAlertService.scan_executives(db)

        data = []
        for a in alerts:
            if isinstance(a, ExecutiveAlert):
                data.append(ExecutiveAlertSchema.model_validate(a).model_dump())
            elif isinstance(a, dict):
                data.append(a)

        if not data:
            data = [{
                "status": "no_alert",
                "message": "未检测到高管减持违规情况",
                "executive_count_scanned": len(db.query(Employee).filter(Employee.is_executive == True).all()),
            }]

        return APIResponse(
            data={"alerts": data, "count": len(data)},
            message=f"高管减持监控扫描完成: 发现{len(data)}项预警",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"高管减持扫描失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=PaginatedResponse)
def list_alerts(
    employee_id: Optional[str] = Query(None),
    alert_type: Optional[str] = Query(None, description="预警类型: 5pct_disclosure/quarterly_limit/annual_limit"),
    is_active: Optional[bool] = Query(None),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(ExecutiveAlert)
    if employee_id:
        query = query.filter(ExecutiveAlert.employee_id == employee_id)
    if alert_type:
        query = query.filter(ExecutiveAlert.alert_type == alert_type)
    if is_active is not None:
        query = query.filter(ExecutiveAlert.is_active == is_active)
    total = query.count()
    alerts = query.order_by(ExecutiveAlert.created_at.desc()).offset(skip).limit(limit).all()
    return PaginatedResponse(
        data=[ExecutiveAlertSchema.model_validate(a).model_dump() for a in alerts],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{alert_id}", response_model=APIResponse)
def get_alert(alert_id: str, db: Session = Depends(get_db)):
    alert = db.query(ExecutiveAlert).filter(ExecutiveAlert.alert_id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail=f"预警记录不存在: {alert_id}")
    data = ExecutiveAlertSchema.model_validate(alert).model_dump()
    if alert.announcement_draft:
        try:
            import json
            data["announcement"] = json.loads(alert.announcement_draft) if isinstance(alert.announcement_draft, str) else alert.announcement_draft
        except Exception:
            data["announcement_raw"] = str(alert.announcement_draft)
    return APIResponse(data=data)


@router.get("/{alert_id}/announcement", response_model=APIResponse)
def get_announcement_draft(alert_id: str, db: Session = Depends(get_db)):
    alert = db.query(ExecutiveAlert).filter(ExecutiveAlert.alert_id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail=f"预警记录不存在: {alert_id}")
    try:
        import json
        draft = json.loads(alert.announcement_draft) if isinstance(alert.announcement_draft, str) else alert.announcement_draft
    except Exception:
        draft = {"raw_text": str(alert.announcement_draft)}
    return APIResponse(data={
        "alert_id": alert_id,
        "employee_id": alert.employee_id,
        "alert_type": alert.alert_type,
        "announcement_draft": draft,
        "created_at": alert.created_at,
    })


@router.post("/{alert_id}/acknowledge", response_model=APIResponse)
def acknowledge_alert(
    alert_id: str,
    operator_id: str = Query("admin", description="确认人ID"),
    operator_name: str = Query("管理员", description="确认人姓名"),
    remarks: Optional[str] = Query(None, description="备注"),
    db: Session = Depends(get_db),
):
    try:
        alert = ExecutiveAlertService.acknowledge_alert(
            db, alert_id, operator_id, operator_name, remarks
        )
        return APIResponse(
            data=ExecutiveAlertSchema.model_validate(alert).model_dump(),
            message=f"预警已确认处理: {alert_id}",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"确认预警失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/simulate", response_model=APIResponse)
def simulate_holding_change(
    employee_id: str = Query(..., description="高管ID"),
    current_holding: float = Query(..., description="当前持股数"),
    planned_sale: float = Query(..., description="计划减持数"),
    total_shares: float = Query(100000000, description="公司总股本"),
    db: Session = Depends(get_db),
):
    from decimal import Decimal
    from services.executive_alert import ExecutiveMonitor
    employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail=f"高管不存在: {employee_id}")
    if not employee.is_executive:
        employee.is_executive = True
        db.commit()

    holding_decimal = Decimal(str(current_holding))
    sale_decimal = Decimal(str(planned_sale))
    total_decimal = Decimal(str(total_shares))

    current_pct = (holding_decimal / total_decimal) * Decimal("100")
    after_pct = ((holding_decimal - sale_decimal) / total_decimal) * Decimal("100")

    result = ExecutiveMonitor.check_three_percent_disclosure(
        holding_decimal, total_decimal, sale_decimal
    )

    quarterly_limit = holding_decimal * Decimal("0.25")
    annual_limit = holding_decimal * Decimal("0.25")

    return APIResponse(data={
        "employee_id": employee_id,
        "employee_name": employee.name,
        "current_holding": float(holding_decimal),
        "planned_sale": float(sale_decimal),
        "total_shares": float(total_decimal),
        "current_holding_pct": float(current_pct),
        "after_sale_holding_pct": float(after_pct),
        "sale_pct_of_total": float((sale_decimal / total_decimal) * Decimal("100")),
        "quarterly_limit_shares": float(quarterly_limit),
        "annual_limit_shares": float(annual_limit),
        "exceeds_quarterly_limit": sale_decimal > quarterly_limit,
        "exceeds_annual_limit": sale_decimal > annual_limit,
        "crosses_5pct_threshold": result["crosses_threshold"],
        "requires_disclosure": result["requires_disclosure"],
        "holding_change_result": result,
    })
