from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from services import AgreementService, GrantService
from schemas import AgreementSchema, APIResponse
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/agreements", tags=["协议管理"])
logger = get_logger("api_agreement")


@router.post("/grant/{grant_id}", response_model=APIResponse)
def generate_grant_agreement(grant_id: str, db: Session = Depends(get_db)):
    grant = GrantService.get_grant(db, grant_id)
    if not grant:
        raise HTTPException(status_code=404, detail="授予记录不存在")

    try:
        agreement = AgreementService.generate_grant_agreement(db, grant)
        return APIResponse(
            data=AgreementSchema.model_validate(agreement).model_dump(),
            message="协议已生成",
        )
    except Exception as e:
        logger.error(f"生成协议失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{agreement_id}/send", response_model=APIResponse)
def send_agreement(agreement_id: str, db: Session = Depends(get_db)):
    try:
        agreement = AgreementService.send_agreement(db, agreement_id)
        return APIResponse(
            data=AgreementSchema.model_validate(agreement).model_dump(),
            message="协议已发送给员工",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{agreement_id}/sign", response_model=APIResponse)
def sign_agreement(
    agreement_id: str,
    signer_id: str,
    signer_name: str,
    db: Session = Depends(get_db),
):
    try:
        agreement = AgreementService.sign_agreement(
            db, agreement_id, signer_id, signer_name
        )
        AgreementService.archive_agreement(db, agreement_id)
        return APIResponse(
            data=AgreementSchema.model_validate(agreement).model_dump(),
            message="协议已签署并归档",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{agreement_id}/archive", response_model=APIResponse)
def archive_agreement(agreement_id: str, db: Session = Depends(get_db)):
    try:
        agreement = AgreementService.archive_agreement(db, agreement_id)
        return APIResponse(
            data=AgreementSchema.model_validate(agreement).model_dump(),
            message="协议已归档",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
