from typing import Optional, List, Dict, Any
from decimal import Decimal
from sqlalchemy.orm import Session
from database.models import (
    ShareholderRecord, EquityGrant, VestingStatus,
    Employee,
)
from utils.common import safe_int, safe_decimal
from utils.logger import get_logger
from utils.operation_log import OperationLogger
from database.models import LogAction, TransactionType

logger = get_logger("shareholder")


class ShareholderService:
    @staticmethod
    def get_record(
        db: Session,
        employee_id: str,
        share_type: str = "COMMON",
    ) -> Optional[ShareholderRecord]:
        return (
            db.query(ShareholderRecord)
            .filter(
                ShareholderRecord.employee_id == employee_id,
                ShareholderRecord.share_type == share_type,
            )
            .first()
        )

    @staticmethod
    def get_or_create_record(
        db: Session,
        employee_id: str,
        share_type: str = "COMMON",
    ) -> ShareholderRecord:
        record = ShareholderService.get_record(db, employee_id, share_type)
        if not record:
            record = ShareholderRecord(
                employee_id=employee_id,
                share_type=share_type,
            )
            db.add(record)
            db.flush()
        return record

    @staticmethod
    def update_record(
        db: Session,
        employee_id: str,
        share_type: str = "COMMON",
    ) -> ShareholderRecord:
        from services.equity_engine import GrantService

        record = ShareholderService.get_or_create_record(db, employee_id, share_type)

        grants = (
            db.query(EquityGrant)
            .filter(
                EquityGrant.employee_id == employee_id,
                EquityGrant.status.in_([
                    VestingStatus.PENDING,
                    VestingStatus.VESTED,
                    VestingStatus.EXERCISED,
                ]),
            )
            .all()
        )

        total_vested = 0
        total_unvested = 0
        total_exercisable = 0
        total_exercised = 0
        total_held = 0
        total_cost = Decimal("0")

        for grant in grants:
            total_unvested += safe_int(grant.shares_outstanding)
            total_vested += safe_int(grant.shares_vested)
            exercisable = GrantService.get_exercisable_shares(db, grant)
            total_exercisable += exercisable
            total_exercised += safe_int(grant.shares_exercised)
            total_held += safe_int(grant.shares_exercised)
            total_cost += safe_decimal(grant.exercise_price) * safe_int(grant.shares_exercised)

        record.total_shares_held = total_held
        record.vested_shares = total_vested
        record.unvested_shares = total_unvested
        record.exercisable_shares = total_exercisable
        record.exercised_shares = total_exercised
        record.shares_available_for_sale = total_held
        record.cost_basis = total_cost

        from datetime import date
        record.last_transaction_date = date.today()

        db.flush()
        return record

    @staticmethod
    def bulk_update_all(db: Session) -> Dict[str, int]:
        employees = db.query(Employee).filter(Employee.is_active == True).all()
        updated = 0
        for emp in employees:
            ShareholderService.update_record(db, emp.employee_id)
            updated += 1
        db.commit()
        logger.info(f"批量更新股东名册完成: {updated} 条记录")
        return {"updated": updated}

    @staticmethod
    def list_shareholders(
        db: Session,
        min_shares: Optional[int] = None,
        share_type: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[ShareholderRecord]:
        query = db.query(ShareholderRecord)
        if min_shares:
            query = query.filter(ShareholderRecord.total_shares_held >= min_shares)
        if share_type:
            query = query.filter(ShareholderRecord.share_type == share_type)
        return (
            query.order_by(ShareholderRecord.total_shares_held.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_executive_shareholders(db: Session) -> List[Dict[str, Any]]:
        results = (
            db.query(ShareholderRecord, Employee)
            .join(Employee, ShareholderRecord.employee_id == Employee.employee_id)
            .filter(Employee.is_executive == True)
            .all()
        )
        return [
            {
                "employee_id": record.employee_id,
                "employee_name": emp.name,
                "position": emp.position,
                "level": emp.level.value,
                "total_shares_held": record.total_shares_held,
                "vested_shares": record.vested_shares,
                "unvested_shares": record.unvested_shares,
                "exercisable_shares": record.exercisable_shares,
                "exercised_shares": record.exercised_shares,
                "shares_available_for_sale": record.shares_available_for_sale,
                "cost_basis": float(record.cost_basis),
                "last_transaction_date": record.last_transaction_date.isoformat() if record.last_transaction_date else None,
            }
            for record, emp in results
        ]

    @staticmethod
    def sync_external_register(db: Session, employee_id: str) -> bool:
        from datetime import datetime
        record = ShareholderService.get_record(db, employee_id)
        if not record:
            return False

        OperationLogger.log(
            db=db,
            action=LogAction.SYNC,
            resource_type="shareholder_record",
            resource_id=employee_id,
            operator_id="system",
            employee_id=employee_id,
            description=f"同步股东名册到外部系统: {employee_id}",
        )
        logger.info(f"已同步股东名册: {employee_id}")
        return True
