from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from services import ShareholderService
from schemas import ShareholderRecordSchema, APIResponse, PaginatedResponse
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/shareholders", tags=["股东名册"])
logger = get_logger("api_shareholder")


@router.get("", response_model=PaginatedResponse)
def list_shareholders(
    min_shares: Optional[int] = None,
    share_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    records = ShareholderService.list_shareholders(db, min_shares, share_type, skip, limit)
    return PaginatedResponse(
        data=[ShareholderRecordSchema.model_validate(r).model_dump() for r in records],
        total=len(records),
        skip=skip,
        limit=limit,
    )


@router.get("/{employee_id}", response_model=APIResponse)
def get_shareholder_record(
    employee_id: str,
    share_type: str = "COMMON",
    db: Session = Depends(get_db),
):
    record = ShareholderService.get_record(db, employee_id, share_type)
    if not record:
        raise HTTPException(status_code=404, detail="股东记录不存在")
    return APIResponse(data=ShareholderRecordSchema.model_validate(record).model_dump())


@router.post("/{employee_id}/update", response_model=APIResponse)
def update_shareholder_record(employee_id: str, db: Session = Depends(get_db)):
    try:
        record = ShareholderService.update_record(db, employee_id)
        db.commit()
        return APIResponse(
            data=ShareholderRecordSchema.model_validate(record).model_dump(),
            message="股东名册已更新",
        )
    except Exception as e:
        db.rollback()
        logger.error(f"更新股东名册失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bulk-update", response_model=APIResponse)
def bulk_update_all(db: Session = Depends(get_db)):
    try:
        result = ShareholderService.bulk_update_all(db)
        return APIResponse(data=result, message="批量更新股东名册完成")
    except Exception as e:
        logger.error(f"批量更新股东名册失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{employee_id}/sync", response_model=APIResponse)
def sync_external_register(employee_id: str, db: Session = Depends(get_db)):
    try:
        result = ShareholderService.sync_external_register(db, employee_id)
        db.commit()
        return APIResponse(data={"success": result}, message="外部系统同步完成")
    except Exception as e:
        db.rollback()
        logger.error(f"同步外部系统失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
