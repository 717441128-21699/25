from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime

from database import get_db
from database.models import EmployeeLevel
from services import EmployeeSyncService
from schemas import (
    EmployeeSchema, EmployeeListResponse, APIResponse, PaginatedResponse, HRSyncResponse,
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
    employees = EmployeeSyncService.list_employees(
        db=db,
        department=department,
        level=level,
        is_active=is_active,
        is_executive=is_executive,
        skip=skip,
        limit=limit,
    )
    total = len(employees) if skip == 0 and limit >= len(employees) else len(employees) + skip
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
        raise HTTPException(status_code=404, detail="员工不存在")
    return APIResponse(data=EmployeeSchema.model_validate(employee).model_dump())


@router.post("/sync", response_model=APIResponse)
async def sync_employees(db: Session = Depends(get_db)):
    try:
        result = await EmployeeSyncService.sync_all_employees(db)
        return APIResponse(data=result, message="HR同步完成")
    except Exception as e:
        logger.error(f"HR同步失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")
