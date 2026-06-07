from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import date

from database import get_db
from services import (
    EquityPlanService, GrantService, GrantCalculator,
    StockPriceService, VestingScheduleGenerator,
)
from schemas import (
    EquityPlanSchema, EquityPlanCreate, EquityGrantSchema,
    GrantCreateRequest, GrantCalculationResponse, APIResponse, PaginatedResponse,
    VestingProcessResponse,
)
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/equity", tags=["股权激励"])
logger = get_logger("api_equity")


@router.get("/plans", response_model=PaginatedResponse)
def list_plans(db: Session = Depends(get_db)):
    plans = EquityPlanService.list_active_plans(db)
    return PaginatedResponse(
        data=[EquityPlanSchema.model_validate(p).model_dump() for p in plans],
        total=len(plans),
    )


@router.post("/plans", response_model=APIResponse)
def create_plan(plan_data: EquityPlanCreate, db: Session = Depends(get_db)):
    try:
        existing = EquityPlanService.get_plan_by_code(db, plan_data.plan_code)
        if existing:
            raise HTTPException(status_code=400, detail="计划编号已存在")

        plan = EquityPlanService.create_plan(db, plan_data.model_dump())
        return APIResponse(
            data=EquityPlanSchema.model_validate(plan).model_dump(),
            message="激励计划创建成功",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建激励计划失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/plans/{plan_id}", response_model=APIResponse)
def get_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = EquityPlanService.get_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="激励计划不存在")
    return APIResponse(data=EquityPlanSchema.model_validate(plan).model_dump())


@router.post("/grants/calculate", response_model=APIResponse)
def calculate_grant(request: GrantCreateRequest, db: Session = Depends(get_db)):
    from services import EmployeeSyncService
    from database.models import Employee

    employee = db.query(Employee).filter(Employee.employee_id == request.employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="员工不存在")

    plan = EquityPlanService.get_plan_by_code(db, request.plan_code)
    if not plan:
        raise HTTPException(status_code=404, detail="激励计划不存在")

    result = GrantCalculator.calculate_grant_amount(
        db=db,
        employee=employee,
        plan=plan,
        custom_shares=request.custom_shares,
        custom_multiplier=request.custom_multiplier,
    )

    exercise_price = request.custom_price or StockPriceService.calculate_grant_price(
        db, plan, request.grant_date
    )

    return APIResponse(data={
        "total_shares": result["total_shares"],
        "calculation_method": result["calculation_method"],
        "exercise_price": float(exercise_price),
        "calculation_details": {k: (float(v) if hasattr(v, '__float__') else v) for k, v in result.items()},
    })


@router.post("/grants", response_model=APIResponse)
def create_grant(request: GrantCreateRequest, db: Session = Depends(get_db)):
    from database.models import Employee

    employee = db.query(Employee).filter(Employee.employee_id == request.employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="员工不存在")

    plan = EquityPlanService.get_plan_by_code(db, request.plan_code)
    if not plan:
        raise HTTPException(status_code=404, detail="激励计划不存在")

    try:
        grant = GrantService.create_grant(
            db=db,
            employee=employee,
            plan=plan,
            grant_date=request.grant_date,
            custom_shares=request.custom_shares,
            custom_price=request.custom_price,
            custom_multiplier=request.custom_multiplier,
        )

        from tasks import generate_agreement_task
        generate_agreement_task.delay(grant.id)

        return APIResponse(
            data=EquityGrantSchema.model_validate(grant).model_dump(),
            message="股权授予成功，协议正在生成中",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"股权授予失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/grants/employee/{employee_id}", response_model=PaginatedResponse)
def get_employee_grants(employee_id: str, db: Session = Depends(get_db)):
    grants = GrantService.get_employee_grants(db, employee_id)
    return PaginatedResponse(
        data=[EquityGrantSchema.model_validate(g).model_dump() for g in grants],
        total=len(grants),
    )


@router.get("/grants/{grant_id}", response_model=APIResponse)
def get_grant(grant_id: str, db: Session = Depends(get_db)):
    grant = GrantService.get_grant(db, grant_id)
    if not grant:
        raise HTTPException(status_code=404, detail="授予记录不存在")
    return APIResponse(data=EquityGrantSchema.model_validate(grant).model_dump())


@router.post("/vesting/process", response_model=APIResponse)
def process_vesting(db: Session = Depends(get_db)):
    try:
        result = GrantService.process_vesting(db)
        return APIResponse(data=result, message="归属处理完成")
    except Exception as e:
        logger.error(f"归属处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock-price/current", response_model=APIResponse)
def get_current_stock_price(db: Session = Depends(get_db)):
    price = StockPriceService.get_current_price(db)
    return APIResponse(data={"current_price": float(price), "currency": "CNY"})
