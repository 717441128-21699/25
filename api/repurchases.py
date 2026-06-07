from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from database.models import RepurchaseRequest, Employee, EquityGrant
from services import RepurchaseService, GrantService
from schemas import (
    RepurchaseCreate, RepurchaseRequestSchema,
    APIResponse, PaginatedResponse,
)
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/repurchases", tags=["股权回购"])
logger = get_logger("api_repurchase")


@router.post("/calculate", response_model=APIResponse)
def calculate_repurchase(request: RepurchaseCreate, db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.employee_id == request.employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail=f"员工不存在: {request.employee_id}")

    grant = GrantService.get_grant(db, request.grant_id)
    if not grant:
        raise HTTPException(status_code=404, detail=f"授予记录不存在: {request.grant_id}")

    from services import RepurchaseCalculator
    from decimal import Decimal

    result = RepurchaseCalculator.calculate(
        db=db,
        grant=grant,
        shares_to_repurchase=request.shares_to_repurchase,
        reason=request.reason,
        custom_price=request.custom_price,
    )

    return APIResponse(data={
        "employee_id": request.employee_id,
        "employee_name": employee.name,
        "grant_id": request.grant_id,
        "shares_to_repurchase": float(request.shares_to_repurchase),
        "repurchase_reason": request.reason.value if hasattr(request.reason, "value") else str(request.reason),
        "repurchase_price_per_share": float(result["price_per_share"]),
        "repurchase_total_amount": float(result["total_amount"]),
        "original_exercise_price": float(result["original_price"]),
        "current_market_price": float(result["current_price"]),
        "price_discount_ratio": float(result["discount_ratio"]),
        "approval_required": result["approval_required"],
        "approval_level": result["approval_level"],
        "board_approval_required": result["board_approval_required"],
        "shareholder_approval_required": result["shareholder_approval_required"],
        "currency": "CNY",
    })


@router.post("", response_model=APIResponse)
def create_repurchase(request: RepurchaseCreate, db: Session = Depends(get_db)):
    try:
        repurchase = RepurchaseService.create_repurchase_request(
            db=db,
            employee_id=request.employee_id,
            grant_id=request.grant_id,
            shares_to_repurchase=request.shares_to_repurchase,
            reason=request.reason,
            custom_price=request.custom_price,
        )
        return APIResponse(
            data=RepurchaseRequestSchema.model_validate(repurchase).model_dump(),
            message=f"回购申请已提交: {repurchase.request_id}, 股数{repurchase.shares_to_repurchase}, 总金额¥{float(repurchase.repurchase_amount):.2f}, 审批级别={repurchase.approval_level}",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"创建回购申请失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=PaginatedResponse)
def list_repurchases(
    employee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    approval_level: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(RepurchaseRequest)
    if employee_id:
        query = query.filter(RepurchaseRequest.employee_id == employee_id)
    if status:
        try:
            from database.models import RepurchaseStatus
            query = query.filter(RepurchaseRequest.status == RepurchaseStatus(status))
        except Exception:
            pass
    if approval_level:
        try:
            from database.models import ApprovalLevel
            query = query.filter(RepurchaseRequest.approval_level == ApprovalLevel(approval_level))
        except Exception:
            pass
    total = query.count()
    repurchases = query.order_by(RepurchaseRequest.created_at.desc()).offset(skip).limit(limit).all()
    return PaginatedResponse(
        data=[RepurchaseRequestSchema.model_validate(r).model_dump() for r in repurchases],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{request_id}", response_model=APIResponse)
def get_repurchase(request_id: str, db: Session = Depends(get_db)):
    repurchase = db.query(RepurchaseRequest).filter(RepurchaseRequest.request_id == request_id).first()
    if not repurchase:
        raise HTTPException(status_code=404, detail=f"回购申请不存在: {request_id}")
    return APIResponse(data=RepurchaseRequestSchema.model_validate(repurchase).model_dump())


@router.post("/{request_id}/approve", response_model=APIResponse)
def approve_repurchase(
    request_id: str,
    approver_id: str = Query("admin", description="审批人ID"),
    approver_name: str = Query("管理员", description="审批人姓名"),
    approval_level: Optional[str] = Query(None, description="审批级别: manager/board/shareholder"),
    db: Session = Depends(get_db),
):
    try:
        from database.models import ApprovalLevel
        level = None
        if approval_level:
            try:
                level = ApprovalLevel(approval_level)
            except Exception:
                level = ApprovalLevel.MANAGER
        repurchase = RepurchaseService.process_approval(
            db, request_id, approver_id, approver_name, True, level
        )
        return APIResponse(
            data=RepurchaseRequestSchema.model_validate(repurchase).model_dump(),
            message=f"回购审批通过: {request_id}, 当前审批进度={len(repurchase.approvals) if hasattr(repurchase, 'approvals') else 1}级",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"审批回购失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{request_id}/complete", response_model=APIResponse)
def complete_repurchase(
    request_id: str,
    executor_id: str = Query("finance", description="执行人ID"),
    executor_name: str = Query("财务", description="执行人姓名"),
    db: Session = Depends(get_db),
):
    try:
        repurchase = RepurchaseService.complete_repurchase(
            db, request_id, executor_id, executor_name
        )
        return APIResponse(
            data=RepurchaseRequestSchema.model_validate(repurchase).model_dump(),
            message=f"回购完成: {request_id}, 回购金额¥{float(repurchase.repurchase_amount):.2f}",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"完成回购失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
