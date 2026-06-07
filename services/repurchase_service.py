from typing import Dict, Any, Optional, List
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy.orm import Session
from database.models import (
    RepurchaseRequest, EquityGrant, Employee,
    RepurchaseStatus, ApprovalLevel, ApprovalStatus,
    ApprovalRecord, VestingStatus, ShareholderRecord,
)
from utils.common import generate_id, safe_decimal, safe_int
from utils.logger import get_logger
from utils.cache import redis_manager
from utils.operation_log import OperationLogger
from database.models import LogAction, TransactionType
from services.equity_engine import StockPriceService
from services.shareholder import ShareholderService

logger = get_logger("repurchase")


class RepurchaseCalculator:
    @staticmethod
    def calculate_repurchase_price(
        db: Session,
        grant: EquityGrant,
        reason_type: str = "TERMINATION",
    ) -> Dict[str, Any]:
        if reason_type == "TERMINATION_FOR_CAUSE":
            price = Decimal("0.01")
            method = "ZERO_VALUE"
        elif reason_type == "VOLUNTARY_TERMINATION":
            if grant.plan and grant.plan.repurchase_price_method == "FMV":
                price = StockPriceService.get_current_price(db) * Decimal("0.8")
                method = "FMV_DISCOUNT_80"
            else:
                price = safe_decimal(grant.exercise_price)
                method = "ORIGINAL_PRICE"
        elif reason_type == "INVOLUNTARY_TERMINATION":
            price = StockPriceService.get_current_price(db)
            method = "FAIR_MARKET_VALUE"
        elif reason_type == "GOOD_LEAVER":
            price = StockPriceService.get_current_price(db) * Decimal("1.0")
            method = "FULL_FMV"
        else:
            price = safe_decimal(grant.exercise_price)
            method = "DEFAULT_ORIGINAL_PRICE"

        return {
            "price_per_share": price,
            "method": method,
            "reason_type": reason_type,
        }

    @staticmethod
    def calculate_employee_repurchase(
        db: Session,
        employee_id: str,
        reason_type: str,
    ) -> Dict[str, Any]:
        grants = (
            db.query(EquityGrant)
            .filter(
                EquityGrant.employee_id == employee_id,
                EquityGrant.status.in_([
                    VestingStatus.PENDING,
                    VestingStatus.VESTED,
                ]),
            )
            .all()
        )

        details = []
        total_shares = 0
        total_amount = Decimal("0")

        for grant in grants:
            price_info = RepurchaseCalculator.calculate_repurchase_price(db, grant, reason_type)
            shares = (
                safe_int(grant.shares_outstanding)
                + safe_int(grant.shares_vested)
                - safe_int(grant.shares_exercised)
            )
            if shares > 0:
                amount = price_info["price_per_share"] * shares
                details.append({
                    "grant_id": grant.grant_id,
                    "shares": shares,
                    "price_per_share": price_info["price_per_share"],
                    "amount": amount,
                    "price_method": price_info["method"],
                })
                total_shares += shares
                total_amount += amount

        return {
            "employee_id": employee_id,
            "reason_type": reason_type,
            "total_shares": total_shares,
            "total_amount": total_amount,
            "currency": "CNY",
            "details": details,
        }


class RepurchaseApprovalEngine:
    BOARD_APPROVAL_THRESHOLD = Decimal("1000000")
    SHAREHOLDER_APPROVAL_THRESHOLD = Decimal("5000000")

    @classmethod
    def determine_approval_levels(cls, total_amount: Decimal) -> List[ApprovalLevel]:
        levels = [ApprovalLevel.MANAGER]
        if total_amount >= cls.BOARD_APPROVAL_THRESHOLD:
            levels.append(ApprovalLevel.BOARD)
        if total_amount >= cls.SHAREHOLDER_APPROVAL_THRESHOLD:
            levels.append(ApprovalLevel.SHAREHOLDER)
        return levels

    @classmethod
    def get_next_approval_level(
        cls,
        request: RepurchaseRequest,
    ) -> Optional[ApprovalLevel]:
        required_levels = cls.determine_approval_levels(
            safe_decimal(request.total_repurchase_amount)
        )

        approvals = {a.approval_level: a.status for a in request.approvals}

        for level in required_levels:
            status = approvals.get(level)
            if status == ApprovalStatus.REJECTED:
                return None
            if status != ApprovalStatus.APPROVED:
                return level

        return None


class RepurchaseService:
    @staticmethod
    def create_repurchase_request(
        db: Session,
        employee_id: str,
        reason_type: str,
        reason: str,
        initiated_by: str,
        initiator_name: str,
    ) -> RepurchaseRequest:
        employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
        if not employee:
            raise ValueError(f"员工不存在: {employee_id}")

        calc = RepurchaseCalculator.calculate_employee_repurchase(db, employee_id, reason_type)

        if calc["total_shares"] <= 0:
            raise ValueError("该员工无可回购股份")

        grant_ids = [d["grant_id"] for d in calc["details"]]

        request = RepurchaseRequest(
            request_id=generate_id("RP"),
            initiated_by=initiated_by,
            employee_id=employee_id,
            grant_ids=grant_ids,
            total_shares=calc["total_shares"],
            repurchase_price_per_share=Decimal("0"),
            total_repurchase_amount=calc["total_amount"],
            currency=calc["currency"],
            reason=reason,
            repurchase_reason_type=reason_type,
            status=RepurchaseStatus.DRAFT,
            metadata={
                "repurchase_details": [
                    {
                        "grant_id": d["grant_id"],
                        "shares": d["shares"],
                        "price_per_share": float(d["price_per_share"]),
                        "amount": float(d["amount"]),
                        "price_method": d["price_method"],
                    }
                    for d in calc["details"]
                ],
            },
        )

        if calc["details"]:
            weighted_sum = sum(d["price_per_share"] * d["shares"] for d in calc["details"])
            request.repurchase_price_per_share = weighted_sum / calc["total_shares"]

        db.add(request)
        db.flush()

        OperationLogger.log(
            db=db,
            action=LogAction.CREATE,
            resource_type="repurchase_request",
            resource_id=request.request_id,
            operator_id=initiated_by,
            operator_name=initiator_name,
            employee_id=employee_id,
            transaction_type=TransactionType.REPURCHASE,
            description=f"创建回购申请: 员工 {employee.name}, {calc['total_shares']} 股, 金额 {float(calc['total_amount'])}",
        )

        db.commit()
        db.refresh(request)
        return request

    @staticmethod
    def submit_for_approval(
        db: Session,
        request_id: str,
        submitter_id: str,
        submitter_name: str,
    ) -> RepurchaseRequest:
        request = (
            db.query(RepurchaseRequest)
            .filter(RepurchaseRequest.request_id == request_id)
            .first()
        )
        if not request:
            raise ValueError(f"回购申请不存在: {request_id}")

        if request.status != RepurchaseStatus.DRAFT:
            raise ValueError(f"申请状态不允许提交审批: {request.status.value}")

        next_level = RepurchaseApprovalEngine.get_next_approval_level(request)
        request.status = RepurchaseStatus.PENDING_APPROVAL
        request.current_approval_level = next_level

        required_levels = RepurchaseApprovalEngine.determine_approval_levels(
            safe_decimal(request.total_repurchase_amount)
        )
        for level in required_levels:
            existing = (
                db.query(ApprovalRecord)
                .filter(
                    ApprovalRecord.repurchase_id == request.id,
                    ApprovalRecord.approval_level == level,
                )
                .first()
            )
            if not existing:
                db.add(ApprovalRecord(
                    repurchase_id=request.id,
                    approval_level=level,
                    approver="待审批",
                    status=ApprovalStatus.PENDING,
                ))

        OperationLogger.log(
            db=db,
            action=LogAction.UPDATE,
            resource_type="repurchase_request",
            resource_id=request.request_id,
            operator_id=submitter_id,
            operator_name=submitter_name,
            employee_id=request.employee_id,
            description=f"提交回购申请审批，需要经过: {[l.value for l in required_levels]}",
        )

        db.commit()
        db.refresh(request)
        return request

    @staticmethod
    def approve_repurchase(
        db: Session,
        request_id: str,
        approver_id: str,
        approver_name: str,
        approval_level: ApprovalLevel,
        comments: Optional[str] = None,
        vote_count: Optional[Dict[str, int]] = None,
    ) -> RepurchaseRequest:
        request = (
            db.query(RepurchaseRequest)
            .filter(RepurchaseRequest.request_id == request_id)
            .first()
        )
        if not request:
            raise ValueError(f"回购申请不存在: {request_id}")

        if request.status != RepurchaseStatus.PENDING_APPROVAL:
            raise ValueError(f"申请状态不允许审批: {request.status.value}")

        approval = (
            db.query(ApprovalRecord)
            .filter(
                ApprovalRecord.repurchase_id == request.id,
                ApprovalRecord.approval_level == approval_level,
            )
            .first()
        )
        if not approval:
            raise ValueError(f"审批记录不存在: {approval_level.value}")

        approval.status = ApprovalStatus.APPROVED
        approval.approver = approver_name
        approval.decision_date = datetime.utcnow()
        approval.comments = comments
        approval.vote_count = vote_count

        if approval_level == ApprovalLevel.BOARD:
            request.status = RepurchaseStatus.BOARD_APPROVED
        elif approval_level == ApprovalLevel.SHAREHOLDER:
            request.status = RepurchaseStatus.SHAREHOLDER_APPROVED

        next_level = RepurchaseApprovalEngine.get_next_approval_level(request)
        if next_level is None:
            request.status = RepurchaseStatus.APPROVED
            request.current_approval_level = None
        else:
            request.current_approval_level = next_level

        OperationLogger.log(
            db=db,
            action=LogAction.APPROVE,
            resource_type="repurchase_request",
            resource_id=request.request_id,
            operator_id=approver_id,
            operator_name=approver_name,
            employee_id=request.employee_id,
            transaction_type=TransactionType.REPURCHASE,
            description=f"{approval_level.value} 审批通过回购申请",
        )

        db.commit()
        db.refresh(request)
        return request

    @staticmethod
    def reject_repurchase(
        db: Session,
        request_id: str,
        rejector_id: str,
        rejector_name: str,
        approval_level: ApprovalLevel,
        reason: str,
    ) -> RepurchaseRequest:
        request = (
            db.query(RepurchaseRequest)
            .filter(RepurchaseRequest.request_id == request_id)
            .first()
        )
        if not request:
            raise ValueError(f"回购申请不存在: {request_id}")

        approval = (
            db.query(ApprovalRecord)
            .filter(
                ApprovalRecord.repurchase_id == request.id,
                ApprovalRecord.approval_level == approval_level,
            )
            .first()
        )
        if approval:
            approval.status = ApprovalStatus.REJECTED
            approval.approver = rejector_name
            approval.decision_date = datetime.utcnow()
            approval.comments = reason

        request.status = RepurchaseStatus.REJECTED
        request.current_approval_level = None

        OperationLogger.log(
            db=db,
            action=LogAction.REJECT,
            resource_type="repurchase_request",
            resource_id=request.request_id,
            operator_id=rejector_id,
            operator_name=rejector_name,
            employee_id=request.employee_id,
            description=f"驳回回购申请: {reason}",
        )

        db.commit()
        db.refresh(request)
        return request

    @staticmethod
    def complete_repurchase(
        db: Session,
        request_id: str,
        operator_id: str,
        operator_name: str,
    ) -> RepurchaseRequest:
        request = (
            db.query(RepurchaseRequest)
            .filter(RepurchaseRequest.request_id == request_id)
            .first()
        )
        if not request:
            raise ValueError(f"回购申请不存在: {request_id}")

        if request.status != RepurchaseStatus.APPROVED:
            raise ValueError(f"申请状态不允许完成: {request.status.value}")

        details = request.metadata.get("repurchase_details", []) if request.metadata else []

        for detail in details:
            grant = (
                db.query(EquityGrant)
                .filter(EquityGrant.grant_id == detail["grant_id"])
                .first()
            )
            if grant:
                shares = detail["shares"]
                grant.shares_forfeited = safe_int(grant.shares_forfeited) + shares
                remaining = (
                    safe_int(grant.shares_outstanding)
                    + safe_int(grant.shares_vested)
                    - safe_int(grant.shares_exercised)
                    - safe_int(grant.shares_forfeited)
                )
                if remaining <= 0:
                    grant.status = VestingStatus.FORFEITED

                if grant.plan:
                    grant.plan.shares_available = (
                        safe_int(grant.plan.shares_available) + shares
                    )

        request.status = RepurchaseStatus.COMPLETED
        request.repurchase_date = date.today()

        ShareholderService.update_record(db, request.employee_id)
        ShareholderService.sync_external_register(db, request.employee_id)

        OperationLogger.log(
            db=db,
            action=LogAction.UPDATE,
            resource_type="repurchase_request",
            resource_id=request.request_id,
            operator_id=operator_id,
            operator_name=operator_name,
            employee_id=request.employee_id,
            transaction_type=TransactionType.REPURCHASE,
            description=f"完成回购: {request.total_shares} 股，支付 {float(request.total_repurchase_amount)}",
        )

        db.commit()
        db.refresh(request)
        return request

    @staticmethod
    def get_repurchase(db: Session, request_id: str) -> Optional[RepurchaseRequest]:
        return (
            db.query(RepurchaseRequest)
            .filter(RepurchaseRequest.request_id == request_id)
            .first()
        )

    @staticmethod
    def list_repurchases(
        db: Session,
        status: Optional[RepurchaseStatus] = None,
        employee_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[RepurchaseRequest]:
        query = db.query(RepurchaseRequest)
        if status:
            query = query.filter(RepurchaseRequest.status == status)
        if employee_id:
            query = query.filter(RepurchaseRequest.employee_id == employee_id)
        return query.order_by(RepurchaseRequest.created_at.desc()).offset(skip).limit(limit).all()
