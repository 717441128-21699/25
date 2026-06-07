from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional

from database import get_db
from database.models import EmployeeLevel, Employee
from services import EmployeeSyncService
from schemas import (
    EmployeeSchema, APIResponse, PaginatedResponse,
)
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/employees", tags=["员工管理"])
logger = get_logger("api_employees")


@router.get("", response_model=PaginatedResponse)
def list_employees(
    department: Optional[str] = Query(None, description="部门筛选"),
    level: Optional[EmployeeLevel] = Query(None, description="员工级别"),
    is_active: Optional[bool] = Query(None, description="是否在职"),
    is_executive: Optional[bool] = Query(None, description="是否高管"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(Employee)
    if department:
        query = query.filter(Employee.department == department)
    if level:
        query = query.filter(Employee.level == level)
    if is_active is not None:
        query = query.filter(Employee.is_active == is_active)
    if is_executive is not None:
        query = query.filter(Employee.is_executive == is_executive)

    total = query.count()
    employees = query.order_by(Employee.employee_id).offset(skip).limit(limit).all()

    return PaginatedResponse(
        data=[EmployeeSchema.model_validate(e).model_dump() for e in employees],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{employee_id}", response_model=APIResponse)
def get_employee(employee_id: str, db: Session = Depends(get_db)):
    employee = EmployeeSyncService.get_employee(db, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail=f"员工不存在: {employee_id}")
    return APIResponse(data=EmployeeSchema.model_validate(employee).model_dump())


@router.post("/sync", response_model=APIResponse)
async def sync_employees(db: Session = Depends(get_db)):
    try:
        result = await EmployeeSyncService.sync_all_employees(db)
        if not result:
            result = {"status": "failed"}
        return APIResponse(
            data=result,
            message=f"HR同步完成: 新增{result.get('created', 0)}人, 更新{result.get('updated', 0)}人, 共{result.get('total', 0)}人"
        )
    except Exception as e:
        logger.error(f"HR同步失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")
