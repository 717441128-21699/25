from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from database.models import Employee, EquityGrant
from services import (
    EquityPlanService, GrantService, GrantCalculator,
    StockPriceService,
)
from schemas import (
    EquityPlanSchema, EquityPlanCreate, EquityGrantSchema,
    GrantCreateRequest, APIResponse, PaginatedResponse,
)
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/equity", tags=["股权激励"])
logger = get_logger("api_equity")


@router.get("/plans", response_model=PaginatedResponse)
def list_plans(db: Session = Depends(get_db)):
    from database.models import EquityPlan
    plans = db.query(EquityPlan).order_by(EquityPlan.id).all()
    return PaginatedResponse(
        data=[EquityPlanSchema.model_validate(p).model_dump() for p in plans],
        total=len(plans),
    )


@router.post("/plans", response_model=APIResponse)
def create_plan(plan_data: EquityPlanCreate, db: Session = Depends(get_db)):
    try:
        existing = EquityPlanService.get_plan_by_code(db, plan_data.plan_code)
        if existing:
            return APIResponse(
                success=True,
                data=EquityPlanSchema.model_validate(existing).model_dump(),
                message=f"激励计划已存在: {plan_data.plan_code}"
            )

        plan = EquityPlanService.create_plan(db, plan_data.model_dump())
        return APIResponse(
            data=EquityPlanSchema.model_validate(plan).model_dump(),
            message="激励计划创建成功",
        )
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
    employee = db.query(Employee).filter(Employee.employee_id == request.employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail=f"员工不存在: {request.employee_id}")

    plan = EquityPlanService.get_plan_by_code(db, request.plan_code)
    if not plan:
        raise HTTPException(status_code=404, detail=f"激励计划不存在: {request.plan_code}")

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

    details = {}
    for k, v in result.items():
        if hasattr(v, '__float__'):
            details[k] = float(v)
        elif isinstance(v, list):
            details[k] = v
        else:
            details[k] = v

    return APIResponse(data={
        "total_shares": result["total_shares"],
        "calculation_method": result["calculation_method"],
        "exercise_price": float(exercise_price),
        "currency": "CNY",
        "calculation_details": details,
    })


@router.post("/grants", response_model=APIResponse)
def create_grant(request: GrantCreateRequest, db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.employee_id == request.employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail=f"员工不存在: {request.employee_id}")

    plan = EquityPlanService.get_plan_by_code(db, request.plan_code)
    if not plan:
        raise HTTPException(status_code=404, detail=f"激励计划不存在: {request.plan_code}")

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

        grant.is_accepted = True
        from datetime import date as _date
        grant.acceptance_date = grant.acceptance_date or _date.today()
        db.commit()
        db.refresh(grant)

        try:
            from services import AgreementService
            AgreementService.generate_grant_agreement(db, grant)
        except Exception as agr_e:
            logger.warning(f"自动生成协议失败(不影响授予): {agr_e}")

        return APIResponse(
            data=EquityGrantSchema.model_validate(grant).model_dump(),
            message=f"股权授予成功: {grant.grant_id}, 共{grant.total_shares}股, 行权价¥{float(grant.exercise_price):.2f}",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"股权授予失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/grants/employee/{employee_id}", response_model=PaginatedResponse)
def get_employee_grants(
    employee_id: str,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(EquityGrant).filter(EquityGrant.employee_id == employee_id)
    if status:
        from database.models import VestingStatus
        try:
            query = query.filter(EquityGrant.status == VestingStatus(status))
        except Exception:
            pass
    grants = query.order_by(EquityGrant.grant_date.desc()).all()
    return PaginatedResponse(
        data=[EquityGrantSchema.model_validate(g).model_dump() for g in grants],
        total=len(grants),
    )


@router.get("/grants/{grant_id}", response_model=APIResponse)
def get_grant(grant_id: str, db: Session = Depends(get_db)):
    grant = GrantService.get_grant(db, grant_id)
    if not grant:
        raise HTTPException(status_code=404, detail=f"授予记录不存在: {grant_id}")
    data = EquityGrantSchema.model_validate(grant).model_dump()
    data["exercisable_shares"] = GrantService.get_exercisable_shares(db, grant)
    return APIResponse(data=data)


@router.post("/vesting/process", response_model=APIResponse)
def process_vesting(db: Session = Depends(get_db)):
    try:
        result = GrantService.process_vesting(db)
        return APIResponse(
            data=result,
            message=f"归属处理完成: {result.get('vested_count', 0)}条记录, {result.get('vested_shares', 0)}股"
        )
    except Exception as e:
        logger.error(f"归属处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock-price/current", response_model=APIResponse)
def get_current_stock_price(db: Session = Depends(get_db)):
    from datetime import datetime
    price = StockPriceService.get_current_price(db)
    return APIResponse(data={
        "current_price": float(price),
        "currency": "CNY",
        "query_time": datetime.now().isoformat()
    })
