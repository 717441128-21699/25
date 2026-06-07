from typing import Dict, Any, Optional, List
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy.orm import Session
from database.models import (
    ExecutiveAlert, Employee, ShareholderRecord,
)
from utils.common import generate_id, safe_decimal, safe_int
from utils.logger import get_logger
from utils.operation_log import OperationLogger
from database.models import LogAction, TransactionType

logger = get_logger("executive_alert")


class ExecutiveMonitoringService:
    DISCLOSURE_THRESHOLD = Decimal("0.05")
    SHORT_SWING_PERIOD_DAYS = 180
    ANNUAL_REDUCTION_LIMIT = Decimal("0.25")
    QUARTERLY_REDUCTION_LIMIT = Decimal("0.05")

    @classmethod
    def check_executive_reduction(
        cls,
        db: Session,
        employee_id: str,
        shares_before: int,
        shares_after: int,
        transaction_type: str = "REDUCTION",
    ) -> Dict[str, Any]:
        employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
        if not employee or not employee.is_executive:
            return {"is_executive": False, "triggered": False}

        shares_reduced = max(0, shares_before - shares_after)
        if shares_reduced <= 0:
            return {"is_executive": True, "triggered": False}

        if shares_before == 0:
            percentage = Decimal("0")
        else:
            percentage = Decimal(shares_reduced) / Decimal(shares_before)

        alerts = []

        if percentage >= cls.DISCLOSURE_THRESHOLD:
            alerts.append({
                "type": "DISCLOSURE_THRESHOLD",
                "threshold": float(cls.DISCLOSURE_THRESHOLD * 100),
                "actual": float(percentage * 100),
                "message": f"单次减持比例超过{float(cls.DISCLOSURE_THRESHOLD * 100)}%披露阈值",
            })

        if percentage >= cls.QUARTERLY_REDUCTION_LIMIT:
            alerts.append({
                "type": "QUARTERLY_LIMIT",
                "threshold": float(cls.QUARTERLY_REDUCTION_LIMIT * 100),
                "actual": float(percentage * 100),
                "message": f"减持比例超过季度限制{float(cls.QUARTERLY_REDUCTION_LIMIT * 100)}%",
            })

        if percentage >= cls.ANNUAL_REDUCTION_LIMIT:
            alerts.append({
                "type": "ANNUAL_LIMIT",
                "threshold": float(cls.ANNUAL_REDUCTION_LIMIT * 100),
                "actual": float(percentage * 100),
                "message": f"减持比例超过年度限制{float(cls.ANNUAL_REDUCTION_LIMIT * 100)}%",
            })

        triggered = len(alerts) > 0

        return {
            "is_executive": True,
            "triggered": triggered,
            "shares_before": shares_before,
            "shares_reduced": shares_reduced,
            "shares_after": shares_after,
            "percentage": float(percentage),
            "alerts": alerts,
        }

    @classmethod
    def create_alert(
        cls,
        db: Session,
        employee_id: str,
        shares_before: int,
        shares_reduced: int,
        shares_after: int,
        alert_type: str,
        threshold_value: Decimal,
        actual_value: Decimal,
        operator_id: str = "system",
    ) -> ExecutiveAlert:
        employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
        if not employee:
            raise ValueError(f"员工不存在: {employee_id}")

        percentage_reduced = Decimal("0")
        if shares_before > 0:
            percentage_reduced = (Decimal(shares_reduced) / Decimal(shares_before)) * 100

        announcement = cls._generate_announcement_draft(
            employee=employee,
            shares_before=shares_before,
            shares_reduced=shares_reduced,
            shares_after=shares_after,
            percentage_reduced=percentage_reduced,
            alert_type=alert_type,
        )

        alert = ExecutiveAlert(
            alert_id=generate_id("ALT"),
            employee_id=employee_id,
            employee_name=employee.name,
            alert_type=alert_type,
            threshold_value=threshold_value,
            actual_value=actual_value,
            percentage_reduced=percentage_reduced,
            total_shares_before=shares_before,
            shares_reduced=shares_reduced,
            total_shares_after=shares_after,
            announcement_draft=announcement,
            is_approved=False,
        )

        db.add(alert)
        db.flush()

        OperationLogger.log(
            db=db,
            action=LogAction.ALERT,
            resource_type="executive_alert",
            resource_id=alert.alert_id,
            operator_id=operator_id,
            employee_id=employee_id,
            description=f"高管减持预警触发: {alert_type}, 减持{shares_reduced}股，比例{float(percentage_reduced):.2f}%",
        )

        db.commit()
        db.refresh(alert)
        return alert

    @classmethod
    def _generate_announcement_draft(
        cls,
        employee: Employee,
        shares_before: int,
        shares_reduced: int,
        shares_after: int,
        percentage_reduced: Decimal,
        alert_type: str,
    ) -> str:
        today = date.today().strftime("%Y年%m月%d日")

        return f"""
关于公司高管持股变动的公告（草稿）

证券代码: XXXXXX
证券简称: 示例科技
公告编号: {today}-{generate_id('ANNO')[:8]}

本公司及董事会全体成员保证公告内容真实、准确和完整，不存在虚假记载、
误导性陈述或者重大遗漏。

一、股东基本情况
股东姓名: {employee.name}
职务: {employee.position}
员工编号: {employee.employee_id}
是否为公司董事、监事、高级管理人员: 是

二、本次持股变动情况
变动日期: {today}
变动方式: 集中竞价交易/大宗交易
变动前持股数量: {shares_before:,} 股
变动数量: -{shares_reduced:,} 股
变动后持股数量: {shares_after:,} 股
变动比例: {float(percentage_reduced):.4f}%

三、其他说明
{cls._get_alert_description(alert_type, percentage_reduced)}

四、承诺事项
本公司将持续关注上述股东持股变动情况，并按照相关法律法规的规定
及时履行信息披露义务。

特此公告。

示例科技有限公司董事会
{today}
"""

    @classmethod
    def _get_alert_description(cls, alert_type: str, percentage: Decimal) -> str:
        if alert_type == "DISCLOSURE_THRESHOLD":
            return f"本次减持比例达到5%的披露阈值，根据《上市公司股东、董监高减持股份的若干规定》，需及时履行信息披露义务。"
        elif alert_type == "QUARTERLY_LIMIT":
            return f"本次减持比例{float(percentage):.2f}%已超过董监高季度减持不超过5%的限制，合规部门需重点关注。"
        elif alert_type == "ANNUAL_LIMIT":
            return f"本次减持比例{float(percentage):.2f}%已超过董监高年度减持不超过25%的限制，可能触发监管关注。"
        return "请合规部门审核本次持股变动的合规性。"

    @classmethod
    def approve_alert(
        cls,
        db: Session,
        alert_id: str,
        approver_id: str,
        approver_name: str,
    ) -> ExecutiveAlert:
        alert = (
            db.query(ExecutiveAlert)
            .filter(ExecutiveAlert.alert_id == alert_id)
            .first()
        )
        if not alert:
            raise ValueError(f"预警记录不存在: {alert_id}")

        alert.is_approved = True
        alert.approved_by = approver_name
        alert.approved_at = datetime.utcnow()

        OperationLogger.log(
            db=db,
            action=LogAction.APPROVE,
            resource_type="executive_alert",
            resource_id=alert_id,
            operator_id=approver_id,
            operator_name=approver_name,
            employee_id=alert.employee_id,
            description="合规部门已审核通过高管减持公告草稿",
        )

        db.commit()
        db.refresh(alert)
        return alert

    @classmethod
    def list_pending_alerts(
        cls,
        db: Session,
        skip: int = 0,
        limit: int = 100,
    ) -> List[ExecutiveAlert]:
        return (
            db.query(ExecutiveAlert)
            .filter(ExecutiveAlert.is_approved == False)
            .order_by(ExecutiveAlert.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    @classmethod
    def monitor_all_executives(cls, db: Session) -> List[Dict[str, Any]]:
        from services.shareholder import ShareholderService

        results = []
        executives = ShareholderService.get_executive_shareholders(db)

        for exec_data in executives:
            total = exec_data["total_shares_held"]
            available = exec_data["shares_available_for_sale"]
            if total > 0:
                ratio = Decimal(available) / Decimal(total)
                if ratio >= cls.QUARTERLY_REDUCTION_LIMIT:
                    results.append({
                        "employee_id": exec_data["employee_id"],
                        "employee_name": exec_data["employee_name"],
                        "position": exec_data["position"],
                        "total_shares": total,
                        "available_shares": available,
                        "available_ratio": float(ratio * 100),
                        "warning": f"可售股份占比达{float(ratio * 100):.2f}%，接近季度减持限制",
                    })

        return results
