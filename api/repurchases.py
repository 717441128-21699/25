from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, List

from database import get_db
from services import (
    RepurchaseService, RepurchaseCalculator, RepurchaseApprovalEngine,
)
from database.models import RepurchaseStatus, ApprovalLevel
from schemas import (
    RepurchaseRequestCreate, RepurchaseRequestSchema,
    RepurchaseApprovalRequest, APIResponse, PaginatedResponse,
)
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/repurchases", tags=["回购管理"])
logger = get_logger("api_repurchase")


@router.post("/calculate", response_model=APIResponse)
def calculate_repurchase(
    employee_id: str,
    reason_type: str = "VOLUNTARY_TERMINATION",
    db: Session = Depends(get_db),
):
    try:
        result = RepurchaseCalculator.calculate_employee_repurchase(
            db, employee_id, reason_type
        )
        result["total_amount"] = float(result["total_amount"])
        result["currency"] = result.get("currency", "CNY")
        for d in result.get("details", []):
            d["price_per_share"] = float(d["price_per_share"])
            d["amount"] = float(d["amount"])

        required_levels = RepurchaseApprovalEngine.determine_approval_levels(result["total_amount"])
        result["required_approval_levels"] = [l.value for l in required_levels]

        return APIResponse(data=result)
    except Exception as e:
        logger.error(f"计算回购失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=APIResponse)
def create_repurchase_request(
    request: RepurchaseRequestCreate,
    initiated_by: str = "admin",
    initiator_name: str = "管理员",
    db: Session = Depends(get_db),
):
    try:
        repurchase = RepurchaseService.create_repurchase_request(
            db=db,
            employee_id=request.employee_id,
            reason_type=request.reason_type,
            reason=request.reason,
            initiated_by=initiated_by,
            initiator_name=initiator_name,
        )
        return APIResponse(
            data=RepurchaseRequestSchema.model_validate(repurchase).model_dump(),
            message="回购申请已创建",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"创建回购申请失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{request_id}/submit", response_model=APIResponse)
def submit_for_approval(
    request_id: str,
    submitter_id: str = "admin",
    submitter_name: str = "管理员",
    db: Session = Depends(get_db),
):
    try:
        repurchase = RepurchaseService.submit_for_approval(
            db, request_id, submitter_id, submitter_name
        )
        return APIResponse(
            data=RepurchaseRequestSchema.model_validate(repurchase).model_dump(),
            message="回购申请已提交审批",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{request_id}/approve", response_model=APIResponse)
def approve_repurchase(
    request_id: str,
    approval: RepurchaseApprovalRequest,
    approver_id: str = "admin",
    approver_name: str = "管理员",
    db: Session = Depends(get_db),
):
    try:
        repurchase = RepurchaseService.approve_repurchase(
            db=db,
            request_id=request_id,
            approver_id=approver_id,
            approver_name=approver_name,
            approval_level=approval.approval_level,
            comments=approval.comments,
            vote_count=approval.vote_count,
        )
        next_level = RepurchaseApprovalEngine.get_next_approval_level(repurchase)
        msg = f"{approval.approval_level.value} 审批通过"
        if next_level:
            msg += f"，等待下一级审批: {next_level.value}"
        else:
            msg += "，所有审批已完成"
        return APIResponse(
            data=RepurchaseRequestSchema.model_validate(repurchase).model_dump(),
            message=msg,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{request_id}/reject", response_model=APIResponse)
def reject_repurchase(
    request_id: str,
    reason: str,
    approval_level: ApprovalLevel,
    rejector_id: str = "admin",
    rejector_name: str = "管理员",
    db: Session = Depends(get_db),
):
    try:
        repurchase = RepurchaseService.reject_repurchase(
            db, request_id, rejector_id, rejector_name, approval_level, reason
        )
        return APIResponse(
            data=RepurchaseRequestSchema.model_validate(repurchase).model_dump(),
            message="回购申请已驳回",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{request_id}/complete", response_model=APIResponse)
def complete_repurchase(
    request_id: str,
    operator_id: str = "admin",
    operator_name: str = "管理员",
    db: Session = Depends(get_db),
):
    try:
        repurchase = RepurchaseService.complete_repurchase(
            db, request_id, operator_id, operator_name
        )
        return APIResponse(
            data=RepurchaseRequestSchema.model_validate(repurchase).model_dump(),
            message="回购已完成",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=PaginatedResponse)
def list_repurchases(
    status: Optional[RepurchaseStatus] = None,
    employee_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    repurchases = RepurchaseService.list_repurchases(db, status, employee_id, skip, limit)
    return PaginatedResponse(
        data=[RepurchaseRequestSchema.model_validate(r).model_dump() for r in repurchases],
        total=len(repurchases),
        skip=skip,
        limit=limit,
    )


@router.get("/{request_id}", response_model=APIResponse)
def get_repurchase(request_id: str, db: Session = Depends(get_db)):
    repurchase = RepurchaseService.get_repurchase(db, request_id)
    if not repurchase:
        raise HTTPException(status_code=404, detail="回购申请不存在")
    return APIResponse(data=RepurchaseRequestSchema.model_validate(repurchase).model_dump())
