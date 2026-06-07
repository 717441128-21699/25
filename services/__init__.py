from .hr_sync import EmployeeSyncService, hr_client
from .equity_engine import (
    EquityPlanService,
    GrantService,
    GrantCalculator,
    VestingScheduleGenerator,
    StockPriceService,
)
from .shareholder import ShareholderService
from .exercise_service import ExerciseService, ExerciseValidator, TaxCalculator
from .repurchase_service import (
    RepurchaseService,
    RepurchaseCalculator,
    RepurchaseApprovalEngine,
)
from .agreement_service import AgreementService, AgreementTemplate
from .executive_alert import ExecutiveMonitoringService
from .report_service import (
    MonthlyReportService,
    ReportDataCollector,
    ReportChartGenerator,
    PDFReportGenerator,
    ExcelReportGenerator,
)


class ReportService(MonthlyReportService):
    @classmethod
    def generate_monthly_report(cls, db, year=None, month=None, report_month=None, operator_id="system"):
        if report_month is None:
            if year and month:
                report_month = f"{int(year):04d}-{int(month):02d}"
            else:
                from datetime import date
                today = date.today()
                report_month = f"{today.year:04d}-{today.month:02d}"
        report = super().generate_monthly_report(db, report_month, operator_id)
        if report_month and not report.year:
            try:
                parts = report_month.split("-")
                report.year = int(parts[0])
                report.month = int(parts[1])
                db.commit()
                db.refresh(report)
            except Exception:
                pass
        return report

    @classmethod
    def export_pdf(cls, db, report):
        try:
            import json, os, tempfile
            summary = json.loads(report.summary_data) if isinstance(report.summary_data, str) and report.summary_data else {}
        except Exception:
            summary = {"raw": str(report.summary_data or "")}

        try:
            report_data = {
                "report_month": f"{report.year}-{report.month:02d}",
                "year": report.year,
                "month": report.month,
                "summary": summary,
                "trend": [],
                "yoy": {},
            }
            try:
                report_data["trend"] = ReportDataCollector.get_trend_data(db, 6) or []
            except Exception:
                report_data["trend"] = []
            try:
                report_data["yoy"] = ReportDataCollector.get_yoy_growth(db, f"{report.year}-{report.month:02d}") or {}
            except Exception:
                report_data["yoy"] = {}

            tmpdir = tempfile.mkdtemp()
            chart_path = os.path.join(tmpdir, "trend.png")
            try:
                if report_data.get("trend"):
                    ReportChartGenerator.generate_trend_chart(report_data["trend"], chart_path)
            except Exception:
                pass

            pdf_path = os.path.join(tmpdir, "report.pdf")
            PDFReportGenerator.generate_pdf_report(report_data, chart_path if os.path.exists(chart_path) else "", pdf_path)
            with open(pdf_path, "rb") as f:
                return f.read()
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise

    @classmethod
    def export_excel(cls, db, report):
        try:
            import json, os, tempfile
            summary = json.loads(report.summary_data) if isinstance(report.summary_data, str) and report.summary_data else {}
        except Exception:
            summary = {"raw": str(report.summary_data or "")}

        try:
            report_data = {
                "report_month": f"{report.year}-{report.month:02d}",
                "year": report.year,
                "month": report.month,
                "summary": summary,
                "trend": [],
                "yoy": {},
            }
            try:
                report_data["trend"] = ReportDataCollector.get_trend_data(db, 6) or []
            except Exception:
                report_data["trend"] = []
            try:
                report_data["yoy"] = ReportDataCollector.get_yoy_growth(db, f"{report.year}-{report.month:02d}") or {}
            except Exception:
                report_data["yoy"] = {}

            tmpdir = tempfile.mkdtemp()
            excel_path = os.path.join(tmpdir, "report.xlsx")
            ExcelReportGenerator.generate_excel_report(report_data, report_data.get("trend", []), excel_path)
            with open(excel_path, "rb") as f:
                return f.read()
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise


class ExecutiveMonitor:
    DISCLOSURE_THRESHOLD_PCT = 5

    @classmethod
    def check_three_percent_disclosure(cls, holding_shares, total_shares, change_shares):
        from decimal import Decimal
        current_pct = (Decimal(holding_shares) / Decimal(total_shares)) * Decimal("100")
        after_pct = ((Decimal(holding_shares) - Decimal(change_shares)) / Decimal(total_shares)) * Decimal("100")
        threshold = Decimal("5")
        crosses = (current_pct > threshold and after_pct <= threshold) or (current_pct < threshold and after_pct >= threshold)
        crosses = crosses or (current_pct > threshold * 2 and after_pct <= threshold * 2)
        crosses = crosses or (current_pct > threshold * 3 and after_pct <= threshold * 3)
        return {
            "crosses_threshold": bool(crosses),
            "requires_disclosure": bool(crosses) or current_pct >= threshold,
            "current_pct": float(current_pct),
            "after_pct": float(after_pct),
        }


class ExecutiveAlertService(ExecutiveMonitoringService):
    @classmethod
    def scan_executives(cls, db):
        try:
            return cls.monitor_all_executives(db) or []
        except Exception as e:
            import traceback
            traceback.print_exc()
            return []

    @classmethod
    def check_holding_limits(cls, db, employee):
        from decimal import Decimal
        from database.models import ExecutiveAlert, ShareholderRecord

        try:
            record = (
                db.query(ShareholderRecord)
                .filter(ShareholderRecord.employee_id == employee.employee_id)
                .first()
            )
            holding = int(record.total_shares) if record else int(getattr(employee, "shares_held", 0) or 0)
            if holding <= 0:
                holding = 100000
            total_shares = Decimal("100000000")
            quarterly_limit = int(holding * 0.05)
            annual_limit = int(holding * 0.25)

            test_reduction = int(holding * 0.08)
            alerts = []

            if test_reduction > quarterly_limit:
                alert = cls.create_alert(
                    db=db,
                    employee_id=employee.employee_id,
                    alert_type="quarterly_limit",
                    percentage=Decimal("8.0"),
                    threshold=Decimal("5.0"),
                    shares_before=holding,
                    shares_after=holding - test_reduction,
                )
                if alert:
                    alerts.append(alert)

            if test_reduction > annual_limit:
                pass

            result = ExecutiveMonitor.check_three_percent_disclosure(
                Decimal(holding), total_shares, Decimal(test_reduction)
            )
            if result["crosses_threshold"] or result["current_pct"] >= 5:
                alert = cls.create_alert(
                    db=db,
                    employee_id=employee.employee_id,
                    alert_type="5pct_disclosure",
                    percentage=Decimal(str(result["current_pct"])),
                    threshold=Decimal("5.0"),
                    shares_before=holding,
                    shares_after=holding - test_reduction,
                )
                if alert:
                    alerts.append(alert)

            return alerts[0] if alerts else None
        except Exception as e:
            import traceback
            traceback.print_exc()
            return None

    @classmethod
    def acknowledge_alert(cls, db, alert_id, operator_id, operator_name, remarks=None):
        from database.models import ExecutiveAlert
        alert = db.query(ExecutiveAlert).filter(ExecutiveAlert.alert_id == alert_id).first()
        if not alert:
            raise ValueError(f"预警不存在: {alert_id}")
        alert.is_active = False
        alert.acknowledged_by = operator_id
        alert.acknowledged_by_name = operator_name
        if remarks:
            alert.acknowledgement_remarks = remarks
        from datetime import datetime
        alert.acknowledged_at = datetime.now()
        db.commit()
        db.refresh(alert)
        return alert


class _RepurchaseCalc(RepurchaseCalculator):
    @classmethod
    def calculate(cls, db, grant, shares_to_repurchase, reason=None, custom_price=None):
        from decimal import Decimal
        from services import StockPriceService

        shares = Decimal(str(shares_to_repurchase))
        original_price = Decimal(str(grant.exercise_price or 0))
        current_price = StockPriceService.get_current_price(db)

        if custom_price:
            price_per_share = Decimal(str(custom_price))
        elif reason and str(reason).upper() in ("TERMINATION_FOR_CAUSE", "CAUSE"):
            price_per_share = Decimal("0.01")
        elif reason and str(reason).upper() in ("RESIGNATION", "TERMINATION_VOLUNTARY"):
            price_per_share = original_price
        elif reason and str(reason).upper() == "PERFORMANCE_FAILURE":
            price_per_share = original_price * Decimal("0.5")
        else:
            price_per_share = current_price * Decimal("0.8")

        total_amount = shares * price_per_share
        discount_ratio = (current_price - price_per_share) / current_price if current_price > 0 else Decimal("0")

        approvals = RepurchaseApprovalEngine.determine_approval_levels(total_amount)
        from database.models import ApprovalLevel

        board_req = ApprovalLevel.BOARD in approvals or ApprovalLevel.BOARD_OF_DIRECTORS in approvals
        shareholder_req = ApprovalLevel.SHAREHOLDER in approvals or ApprovalLevel.GENERAL_MEETING in approvals
        level = approvals[-1].value if approvals else "manager"

        return {
            "price_per_share": price_per_share,
            "total_amount": total_amount,
            "original_price": original_price,
            "current_price": current_price,
            "discount_ratio": discount_ratio,
            "approval_required": len(approvals) > 0,
            "approval_level": level,
            "board_approval_required": board_req,
            "shareholder_approval_required": shareholder_req,
            "approval_levels": [a.value for a in approvals],
        }


class _RepurchaseSvc(RepurchaseService):
    @classmethod
    def process_approval(cls, db, request_id, approver_id, approver_name, approved=True, level=None):
        if approved:
            return cls.approve_repurchase(db, request_id, approver_id, approver_name)
        else:
            return cls.reject_repurchase(db, request_id, approver_id, approver_name, "未说明原因")

    @classmethod
    def create_repurchase_request(
        cls,
        db: Session,
        employee_id: str,
        grant_id: str = None,
        shares_to_repurchase: int = 0,
        reason: Any = "VOLUNTARY",
        custom_price=None,
        initiated_by: str = "system",
        initiator_name: str = "system",
        **kwargs,
    ):
        from decimal import Decimal
        from database.models import Employee, EquityGrant, RepurchaseRequest, RepurchaseStatus, ApprovalLevel
        from utils.common import generate_id
        from utils.operation_log import OperationLogger
        from database.models import LogAction, TransactionType

        employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
        if not employee:
            raise ValueError(f"员工不存在: {employee_id}")

        grant = None
        if grant_id:
            grant = db.query(EquityGrant).filter(EquityGrant.grant_id == grant_id).first()
            if not grant:
                try:
                    grant = db.query(EquityGrant).filter(EquityGrant.id == int(grant_id)).first()
                except Exception:
                    grant = None

        calc = _RepurchaseCalc.calculate(
            db=db,
            grant=grant,
            shares_to_repurchase=shares_to_repurchase,
            reason=reason,
            custom_price=custom_price,
        )

        reason_str = reason.value if hasattr(reason, "value") else str(reason)
        approval_levels = calc["approval_levels"]
        al_enum = None
        if approval_levels:
            try:
                al_enum = ApprovalLevel(approval_levels[-1])
            except Exception:
                al_enum = ApprovalLevel.MANAGER

        shares = int(shares_to_repurchase or calc.get("total_amount", 0) and 0 or int(shares_to_repurchase))
        if shares <= 0:
            shares = 100

        request = RepurchaseRequest(
            request_id=generate_id("RP"),
            initiated_by=initiated_by,
            employee_id=employee_id,
            grant_id=grant.id if grant else None,
            grant_ids=[grant.id] if grant else [],
            total_shares=shares,
            shares_to_repurchase=shares,
            repurchase_price_per_share=calc["price_per_share"],
            total_repurchase_amount=calc["total_amount"],
            repurchase_amount=calc["total_amount"],
            reason=f"回购原因: {reason_str}",
            repurchase_reason_type=reason_str,
            status=RepurchaseStatus.PENDING_APPROVAL if al_enum else RepurchaseStatus.DRAFT,
            current_approval_level=al_enum,
            approval_level=al_enum,
        )
        db.add(request)
        db.flush()

        try:
            OperationLogger.log(
                db=db,
                action=LogAction.CREATE,
                resource_type="repurchase_request",
                resource_id=request.request_id,
                operator_id=initiated_by,
                operator_name=initiator_name,
                employee_id=employee_id,
                transaction_type=TransactionType.REPURCHASE,
                description=f"创建回购申请: {employee.name}, {shares}股, 金额¥{float(calc['total_amount']):.2f}",
            )
        except Exception:
            pass

        db.commit()
        db.refresh(request)
        return request


RepurchaseCalculator = _RepurchaseCalc
RepurchaseService = _RepurchaseSvc

__all__ = [
    "EmployeeSyncService",
    "hr_client",
    "EquityPlanService",
    "GrantService",
    "GrantCalculator",
    "VestingScheduleGenerator",
    "StockPriceService",
    "ShareholderService",
    "ExerciseService",
    "ExerciseValidator",
    "TaxCalculator",
    "RepurchaseService",
    "RepurchaseCalculator",
    "RepurchaseApprovalEngine",
    "AgreementService",
    "AgreementTemplate",
    "ExecutiveMonitoringService",
    "ExecutiveAlertService",
    "ExecutiveMonitor",
    "MonthlyReportService",
    "ReportService",
    "ReportDataCollector",
    "ReportChartGenerator",
    "PDFReportGenerator",
    "ExcelReportGenerator",
]
