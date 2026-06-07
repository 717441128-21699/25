from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from services import (
    ExerciseService, ExerciseValidator, TaxCalculator, GrantService,
)
from database.models import Employee, EquityGrant
from schemas import (
    ExerciseRequestCreate, ExerciseRequestSchema,
    ExerciseValidationResponse, APIResponse, PaginatedResponse,
)
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/exercises", tags=["行权管理"])
logger = get_logger("api_exercise")


@router.post("/validate", response_model=APIResponse)
def validate_exercise(request: ExerciseRequestCreate, db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.employee_id == request.employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="员工不存在")

    grant = GrantService.get_grant(db, request.grant_id)
    if not grant:
        raise HTTPException(status_code=404, detail="授予记录不存在")

    validation = ExerciseValidator.validate_exercise(
        db, grant, request.shares_to_exercise, employee
    )

    shares_decimal = float(request.shares_to_exercise)
    gross_profit = shares_decimal * (float(validation["current_price"]) - float(validation["exercise_price"]))
    tax_result = TaxCalculator.calculate_tax(max(0, gross_profit))
    total_cost = shares_decimal * float(validation["exercise_price"]) + float(tax_result["tax_amount"])

    return APIResponse(data={
        "is_valid": validation["is_valid"],
        "errors": validation["errors"],
        "warnings": validation["warnings"],
        "exercisable_shares": validation["exercisable_shares"],
        "current_price": float(validation["current_price"]),
        "exercise_price": float(validation["exercise_price"]),
        "price_diff": float(validation["price_diff"]),
        "estimated_gross_profit": max(0, gross_profit),
        "estimated_tax": float(tax_result["tax_amount"]),
        "tax_deferred_amount": float(tax_result["deferred_amount"]),
        "estimated_exercise_cost": shares_decimal * float(validation["exercise_price"]),
        "estimated_total_deduction": total_cost,
        "estimated_net_profit": max(0, gross_profit) - total_cost,
    })


@router.post("", response_model=APIResponse)
@router.post("/apply", response_model=APIResponse)
def create_exercise_request(request: ExerciseRequestCreate, db: Session = Depends(get_db)):
    try:
        exercise = ExerciseService.create_exercise_request(
            db=db,
            employee_id=request.employee_id,
            grant_id=request.grant_id,
            shares_to_exercise=request.shares_to_exercise,
        )
        return APIResponse(
            data=ExerciseRequestSchema.model_validate(exercise).model_dump(),
            message="行权申请已提交",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        logger.error(f"创建行权申请失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{request_id}", response_model=APIResponse)
def get_exercise_request(request_id: str, db: Session = Depends(get_db)):
    from database.models import ExerciseRequest
    exercise = db.query(ExerciseRequest).filter(ExerciseRequest.request_id == request_id).first()
    if not exercise:
        raise HTTPException(status_code=404, detail="行权申请不存在")
    return APIResponse(data=ExerciseRequestSchema.model_validate(exercise).model_dump())


@router.post("/{request_id}/approve", response_model=APIResponse)
def approve_exercise(
    request_id: str,
    approver_id: str = "admin",
    approver_name: str = "管理员",
    db: Session = Depends(get_db),
):
    try:
        exercise = ExerciseService.approve_exercise(
            db, request_id, approver_id, approver_name
        )
        ExerciseService.complete_exercise(db, request_id)
        return APIResponse(
            data=ExerciseRequestSchema.model_validate(exercise).model_dump(),
            message="行权审批通过并完成处理",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"审批行权失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{request_id}/reject", response_model=APIResponse)
def reject_exercise(
    request_id: str,
    reason: str,
    rejector_id: str = "admin",
    rejector_name: str = "管理员",
    db: Session = Depends(get_db),
):
    try:
        exercise = ExerciseService.reject_exercise(
            db, request_id, rejector_id, rejector_name, reason
        )
        return APIResponse(
            data=ExerciseRequestSchema.model_validate(exercise).model_dump(),
            message="行权申请已驳回",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/bulk-complete", response_model=APIResponse)
def bulk_complete_exercises(request_ids: List[str], db: Session = Depends(get_db)):
    from tasks import bulk_exercise_task
    task = bulk_exercise_task.delay(request_ids)
    return APIResponse(
        data={"task_id": task.id, "request_count": len(request_ids)},
        message="批量行权任务已提交后台处理",
    )
