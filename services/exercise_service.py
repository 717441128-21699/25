from typing import Dict, Any, Optional, List
from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session
from database.models import (
    ExerciseRequest, EquityGrant, Employee,
    ExerciseStatus, VestingStatus, ShareholderRecord,
)
from utils.common import generate_id, safe_decimal, safe_int
from utils.logger import get_logger
from utils.cache import redis_manager
from utils.operation_log import OperationLogger
from database.models import LogAction, TransactionType
from services.equity_engine import StockPriceService, GrantService
from services.shareholder import ShareholderService

logger = get_logger("exercise")


class TaxCalculator:
    TAX_BRACKETS = [
        (Decimal("36000"), Decimal("0.03"), Decimal("0")),
        (Decimal("144000"), Decimal("0.10"), Decimal("2520")),
        (Decimal("300000"), Decimal("0.20"), Decimal("16920")),
        (Decimal("420000"), Decimal("0.25"), Decimal("31920")),
        (Decimal("660000"), Decimal("0.30"), Decimal("52920")),
        (Decimal("960000"), Decimal("0.35"), Decimal("85920")),
        (None, Decimal("0.45"), Decimal("181920")),
    ]

    TAX_DEFERRED_LIMIT = Decimal("120000")

    @classmethod
    def calculate_tax(
        cls,
        taxable_amount: Decimal,
        tax_deferred: bool = True,
    ) -> Dict[str, Any]:
        deferred_amount = Decimal("0")
        if tax_deferred and taxable_amount > 0:
            deferred_amount = min(taxable_amount, cls.TAX_DEFERRED_LIMIT)

        actual_taxable = taxable_amount - deferred_amount

        if actual_taxable <= 0:
            return {
                "taxable_amount": taxable_amount,
                "deferred_amount": deferred_amount,
                "actual_taxable": Decimal("0"),
                "tax_rate": Decimal("0"),
                "tax_amount": Decimal("0"),
                "quick_deduction": Decimal("0"),
                "brackets": cls.TAX_BRACKETS,
            }

        tax_rate = Decimal("0")
        quick_deduction = Decimal("0")

        for upper_limit, rate, deduction in cls.TAX_BRACKETS:
            if upper_limit is None or actual_taxable <= upper_limit:
                tax_rate = rate
                quick_deduction = deduction
                break

        tax_amount = (actual_taxable * tax_rate) - quick_deduction
        tax_amount = max(tax_amount, Decimal("0"))

        return {
            "taxable_amount": taxable_amount,
            "deferred_amount": deferred_amount,
            "actual_taxable": actual_taxable,
            "tax_rate": tax_rate,
            "tax_amount": tax_amount,
            "quick_deduction": quick_deduction,
        }


class ExerciseValidator:
    @staticmethod
    def validate_exercise(
        db: Session,
        grant: EquityGrant,
        shares_to_exercise: int,
        employee: Employee,
    ) -> Dict[str, Any]:
        errors = []
        warnings = []

        if not grant.is_accepted:
            errors.append("授予协议尚未签署确认")

        if grant.status not in [VestingStatus.VESTED, VestingStatus.PENDING]:
            errors.append(f"授予状态不允许行权: {grant.status.value}")

        current_date = date.today()
        if current_date < grant.vesting_start_date:
            errors.append("尚未到达首批归属时间")

        if current_date > grant.expiration_date:
            errors.append("授予已过期")

        exercisable = GrantService.get_exercisable_shares(db, grant)
        if shares_to_exercise <= 0:
            errors.append("行权数量必须大于0")
        elif shares_to_exercise > exercisable:
            errors.append(f"可行权数量不足。请求: {shares_to_exercise}, 可用: {exercisable}")

        current_price = StockPriceService.get_current_price(db)
        exercise_price = safe_decimal(grant.exercise_price)
        price_diff = current_price - exercise_price

        if price_diff <= 0:
            warnings.append(f"当前股价({float(current_price)})低于或等于行权价({float(exercise_price)})，行权无收益")

        if not employee.is_active:
            warnings.append("员工已离职，请确认是否继续行权")

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "exercisable_shares": exercisable,
            "current_price": current_price,
            "exercise_price": exercise_price,
            "price_diff": price_diff,
        }


class ExerciseService:
    @staticmethod
    def create_exercise_request(
        db: Session,
        employee_id: str,
        grant_id: str,
        shares_to_exercise: int,
        operator_id: Optional[str] = None,
    ) -> ExerciseRequest:
        employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
        if not employee:
            raise ValueError(f"员工不存在: {employee_id}")

        grant = GrantService.get_grant(db, grant_id)
        if not grant:
            raise ValueError(f"授予不存在: {grant_id}")

        if grant.employee_id != employee_id:
            raise ValueError("该授予不属于此员工")

        validation = ExerciseValidator.validate_exercise(db, grant, shares_to_exercise, employee)
        if not validation["is_valid"]:
            raise ValueError(f"行权校验失败: {'; '.join(validation['errors'])}")

        lock_key = f"exercise_lock:grant_{grant_id}"
        if not redis_manager.acquire_lock(lock_key, timeout=60):
            raise RuntimeError("该授予正在处理其他行权请求，请稍后重试")

        try:
            current_price = validation["current_price"]
            exercise_price = validation["exercise_price"]
            price_diff = validation["price_diff"]

            shares = safe_decimal(shares_to_exercise)
            gross_profit = shares * price_diff
            exercise_cost = shares * exercise_price

            tax_result = TaxCalculator.calculate_tax(gross_profit)

            tax_amount = tax_result["tax_amount"]
            deduction_amount = exercise_cost + tax_amount
            net_payment = gross_profit - tax_amount - exercise_cost

            request = ExerciseRequest(
                request_id=generate_id("EX"),
                employee_id=employee_id,
                grant_id=grant.id,
                request_date=date.today(),
                shares_to_exercise=shares_to_exercise,
                current_stock_price=current_price,
                exercise_price=exercise_price,
                price_diff=price_diff,
                gross_profit=gross_profit,
                tax_deferred_amount=tax_result["deferred_amount"],
                taxable_amount=tax_result["actual_taxable"],
                tax_rate=tax_result["tax_rate"],
                tax_amount=tax_amount,
                exercise_cost=exercise_cost,
                net_payment_amount=net_payment,
                deduction_amount=deduction_amount,
                status=ExerciseStatus.PENDING,
                tax_details={
                    "brackets": [[str(b[0]), float(b[1]), float(b[2])] for b in tax_result.get("brackets", [])],
                    "quick_deduction": float(tax_result.get("quick_deduction", 0)),
                },
                extra_metadata={
                    "warnings": validation["warnings"],
                },
            )

            db.add(request)
            db.flush()

            OperationLogger.log(
                db=db,
                action=LogAction.CREATE,
                resource_type="exercise_request",
                resource_id=request.request_id,
                operator_id=operator_id or employee_id,
                employee_id=employee_id,
                transaction_type=TransactionType.EXERCISE,
                description=f"员工 {employee.name} 申请行权 {shares_to_exercise} 股",
                new_value={
                    "grant_id": grant_id,
                    "shares_to_exercise": shares_to_exercise,
                    "gross_profit": float(gross_profit),
                    "tax_amount": float(tax_amount),
                    "deduction_amount": float(deduction_amount),
                },
            )

            db.commit()
            db.refresh(request)
            return request

        finally:
            redis_manager.release_lock(lock_key)

    @staticmethod
    def approve_exercise(
        db: Session,
        request_id: str,
        approver_id: str,
        approver_name: str,
    ) -> ExerciseRequest:
        from datetime import datetime

        request = (
            db.query(ExerciseRequest)
            .filter(ExerciseRequest.request_id == request_id)
            .first()
        )
        if not request:
            raise ValueError(f"行权申请不存在: {request_id}")

        if request.status != ExerciseStatus.PENDING:
            raise ValueError(f"申请状态不允许审批: {request.status.value}")

        request.status = ExerciseStatus.APPROVED
        request.approved_by = approver_name
        request.approved_at = datetime.utcnow()
        request.deduction_order_id = generate_id("PAY")
        request.deduction_status = "PENDING"

        OperationLogger.log(
            db=db,
            action=LogAction.APPROVE,
            resource_type="exercise_request",
            resource_id=request.request_id,
            operator_id=approver_id,
            operator_name=approver_name,
            employee_id=request.employee_id,
            transaction_type=TransactionType.EXERCISE,
            description=f"审批通过行权申请: {request_id}",
        )

        db.flush()
        return request

    @staticmethod
    def complete_exercise(db: Session, request_id: str) -> ExerciseRequest:
        request = (
            db.query(ExerciseRequest)
            .filter(ExerciseRequest.request_id == request_id)
            .first()
        )
        if not request:
            raise ValueError(f"行权申请不存在: {request_id}")

        if request.status not in [ExerciseStatus.APPROVED, ExerciseStatus.PENDING]:
            raise ValueError(f"申请状态不允许完成: {request.status.value}")

        lock_key = f"exercise_lock:grant_{request.grant_id}"
        if not redis_manager.acquire_lock(lock_key, timeout=60):
            raise RuntimeError("该授予正在处理其他操作，请稍后重试")

        try:
            grant = request.grant
            shares = request.shares_to_exercise

            grant.shares_exercised = safe_int(grant.shares_exercised) + shares
            if grant.shares_vested >= safe_int(grant.shares_exercised) + safe_int(grant.shares_forfeited):
                if safe_int(grant.shares_vested) == safe_int(grant.shares_exercised):
                    grant.status = VestingStatus.EXERCISED

            request.status = ExerciseStatus.COMPLETED
            request.deduction_status = "COMPLETED"
            request.settlement_date = date.today()

            ShareholderService.update_record(db, request.employee_id)
            ShareholderService.sync_external_register(db, request.employee_id)

            OperationLogger.log(
                db=db,
                action=LogAction.UPDATE,
                resource_type="exercise_request",
                resource_id=request.request_id,
                operator_id="system",
                employee_id=request.employee_id,
                transaction_type=TransactionType.EXERCISE,
                description=f"完成行权: {shares} 股，扣款 {float(request.deduction_amount)}",
            )

            db.commit()
            db.refresh(request)
            return request

        finally:
            redis_manager.release_lock(lock_key)

    @staticmethod
    def reject_exercise(
        db: Session,
        request_id: str,
        rejector_id: str,
        rejector_name: str,
        reason: str,
    ) -> ExerciseRequest:
        request = (
            db.query(ExerciseRequest)
            .filter(ExerciseRequest.request_id == request_id)
            .first()
        )
        if not request:
            raise ValueError(f"行权申请不存在: {request_id}")

        request.status = ExerciseStatus.REJECTED
        request.rejection_reason = reason

        OperationLogger.log(
            db=db,
            action=LogAction.REJECT,
            resource_type="exercise_request",
            resource_id=request.request_id,
            operator_id=rejector_id,
            operator_name=rejector_name,
            employee_id=request.employee_id,
            transaction_type=TransactionType.EXERCISE,
            description=f"驳回行权申请: {reason}",
        )

        db.commit()
        db.refresh(request)
        return request

    @staticmethod
    def bulk_process_exercises(db: Session, request_ids: List[str]) -> Dict[str, Any]:
        success = []
        failed = []

        for rid in request_ids:
            try:
                ExerciseService.complete_exercise(db, rid)
                success.append(rid)
            except Exception as e:
                failed.append({"request_id": rid, "error": str(e)})
                logger.error(f"批量行权失败 {rid}: {e}")

        db.commit()
        return {"success": success, "failed": failed, "total": len(request_ids)}
