from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from database.models import Employee, EquityGrant, ExerciseRequest
from services import (
    ExerciseService, ExerciseValidator, TaxCalculator, GrantService,
)
from schemas import (
    ExerciseRequestCreate, ExerciseRequestSchema,
    APIResponse, PaginatedResponse,
)
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/exercises", tags=["行权管理"])
logger = get_logger("api_exercise")


@router.post("/validate", response_model=APIResponse)
def validate_exercise(request: ExerciseRequestCreate, db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.employee_id == request.employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail=f"员工不存在: {request.employee_id}")

    grant = GrantService.get_grant(db, request.grant_id)
    if not grant:
        raise HTTPException(status_code=404, detail=f"授予记录不存在: {request.grant_id}")

    validation = ExerciseValidator.validate_exercise(
        db, grant, request.shares_to_exercise, employee
    )

    from decimal import Decimal
    shares_decimal = Decimal(request.shares_to_exercise)
    current_price = validation["current_price"]
    exercise_price = validation["exercise_price"]
    price_diff = current_price - exercise_price
    gross_profit = shares_decimal * max(Decimal("0"), price_diff)
    tax_result = TaxCalculator.calculate_tax(gross_profit)
    exercise_cost = shares_decimal * exercise_price
    tax_amount = tax_result["tax_amount"]
    total_cost = exercise_cost + tax_amount
    net_profit = gross_profit - total_cost

    return APIResponse(data={
        "is_valid": validation["is_valid"],
        "errors": validation["errors"],
        "warnings": validation["warnings"],
        "exercisable_shares": validation["exercisable_shares"],
        "shares_to_exercise": request.shares_to_exercise,
        "current_price": float(current_price),
        "exercise_price": float(exercise_price),
        "price_diff": float(price_diff),
        "gross_profit": float(gross_profit),
        "tax_deferred_amount": float(tax_result["deferred_amount"]),
        "taxable_amount": float(tax_result["actual_taxable"]),
        "tax_rate": float(tax_result["tax_rate"]),
        "tax_amount": float(tax_amount),
        "exercise_cost": float(exercise_cost),
        "total_deduction": float(total_cost),
        "net_profit": float(net_profit),
        "currency": "CNY",
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
            message=f"行权申请已提交: {exercise.request_id}, 股数{exercise.shares_to_exercise}, 税款¥{float(exercise.tax_amount):.2f}, 总扣款¥{float(exercise.deduction_amount):.2f}",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        logger.error(f"创建行权申请失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=PaginatedResponse)
def list_exercises(
    employee_id: str = Query(None),
    status: str = Query(None),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(ExerciseRequest)
    if employee_id:
        query = query.filter(ExerciseRequest.employee_id == employee_id)
    if status:
        try:
            from database.models import ExerciseStatus
            query = query.filter(ExerciseRequest.status == ExerciseStatus(status))
        except Exception:
            pass
    total = query.count()
    exercises = query.order_by(ExerciseRequest.created_at.desc()).offset(skip).limit(limit).all()
    return PaginatedResponse(
        data=[ExerciseRequestSchema.model_validate(e).model_dump() for e in exercises],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{request_id}", response_model=APIResponse)
def get_exercise_request(request_id: str, db: Session = Depends(get_db)):
    exercise = db.query(ExerciseRequest).filter(ExerciseRequest.request_id == request_id).first()
    if not exercise:
        raise HTTPException(status_code=404, detail=f"行权申请不存在: {request_id}")
    return APIResponse(data=ExerciseRequestSchema.model_validate(exercise).model_dump())


@router.post("/{request_id}/approve", response_model=APIResponse)
def approve_exercise(
    request_id: str,
    approver_id: str = Query("admin", description="审批人ID"),
    approver_name: str = Query("管理员", description="审批人姓名"),
    db: Session = Depends(get_db),
):
    try:
        ExerciseService.approve_exercise(db, request_id, approver_id, approver_name)
        exercise = ExerciseService.complete_exercise(db, request_id)
        return APIResponse(
            data=ExerciseRequestSchema.model_validate(exercise).model_dump(),
            message=f"行权审批通过并完成: {exercise.shares_to_exercise}股, 扣款¥{float(exercise.deduction_amount):.2f}",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"审批行权失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{request_id}/reject", response_model=APIResponse)
def reject_exercise(
    request_id: str,
    reason: str = Query(..., description="驳回原因"),
    rejector_id: str = Query("admin", description="驳回人ID"),
    rejector_name: str = Query("管理员", description="驳回人姓名"),
    db: Session = Depends(get_db),
):
    try:
        exercise = ExerciseService.reject_exercise(
            db, request_id, rejector_id, rejector_name, reason
        )
        return APIResponse(
            data=ExerciseRequestSchema.model_validate(exercise).model_dump(),
            message=f"行权申请已驳回: {reason}",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/bulk-complete", response_model=APIResponse)
def bulk_complete_exercises(request_ids: List[str], db: Session = Depends(get_db)):
    try:
        result = ExerciseService.bulk_process_exercises(db, request_ids)
        return APIResponse(
            data=result,
            message=f"批量行权处理完成: 成功{len(result.get('success', []))}个, 失败{len(result.get('failed', []))}个",
        )
    except Exception as e:
        logger.error(f"批量行权失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
