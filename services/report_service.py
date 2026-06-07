from typing import Dict, Any, Optional, List
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path
import io
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from database.models import (
    MonthlyReport, EquityGrant, ExerciseRequest, RepurchaseRequest,
    EquityPlan, VestingSchedule, Employee, ShareholderRecord,
    VestingStatus, ExerciseStatus, RepurchaseStatus, TransactionType,
)
from utils.common import generate_id, safe_decimal, safe_int
from utils.logger import get_logger
from config import settings
from utils.operation_log import OperationLogger
from database.models import LogAction

logger = get_logger("report")


class ReportDataCollector:
    @staticmethod
    def get_monthly_data(db: Session, report_month: str) -> Dict[str, Any]:
        year, month = map(int, report_month.split("-"))
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)

        grants = (
            db.query(EquityGrant)
            .filter(
                EquityGrant.grant_date >= start_date,
                EquityGrant.grant_date < end_date,
            )
            .all()
        )

        exercises = (
            db.query(ExerciseRequest)
            .filter(
                ExerciseRequest.request_date >= start_date,
                ExerciseRequest.request_date < end_date,
                ExerciseRequest.status.in_([
                    ExerciseStatus.APPROVED,
                    ExerciseStatus.COMPLETED,
                ]),
            )
            .all()
        )

        repurchases = (
            db.query(RepurchaseRequest)
            .filter(
                RepurchaseRequest.repurchase_date >= start_date,
                RepurchaseRequest.repurchase_date < end_date,
                RepurchaseRequest.status == RepurchaseStatus.COMPLETED,
            )
            .all()
        )

        total_grants_shares = sum(g.total_shares for g in grants)
        total_exercises_shares = sum(e.shares_to_exercise for e in exercises)
        total_repurchases_shares = sum(r.total_shares for r in repurchases)

        total_grants_count = len(grants)
        total_exercises_count = len(exercises)
        total_repurchases_count = len(repurchases)

        outstanding = (
            db.query(func.sum(EquityGrant.shares_outstanding))
            .filter(EquityGrant.status.in_([VestingStatus.PENDING, VestingStatus.VESTED]))
            .scalar() or 0
        )

        vested = (
            db.query(func.sum(EquityGrant.shares_vested))
            .scalar() or 0
        )

        exercised = (
            db.query(func.sum(EquityGrant.shares_exercised))
            .scalar() or 0
        )

        plans = db.query(EquityPlan).all()
        inventory = sum(safe_int(p.shares_available) for p in plans)

        active_employees = (
            db.query(func.count(Employee.id))
            .filter(Employee.is_active == True)
            .scalar() or 0
        )

        total_exercise_profit = sum(
            float(e.net_payment_amount) for e in exercises
        )
        avg_profit = Decimal("0")
        if active_employees > 0:
            avg_profit = Decimal(total_exercise_profit) / Decimal(active_employees)

        return {
            "report_month": report_month,
            "total_grants_count": total_grants_count,
            "total_grants_shares": total_grants_shares,
            "total_exercises_count": total_exercises_count,
            "total_exercises_shares": total_exercises_shares,
            "total_repurchases_count": total_repurchases_count,
            "total_repurchases_shares": total_repurchases_shares,
            "inventory_shares": inventory,
            "outstanding_shares": int(outstanding),
            "vested_shares": int(vested),
            "exercised_shares": int(exercised),
            "average_profit_per_employee": avg_profit,
            "total_exercise_profit": total_exercise_profit,
            "active_employees": active_employees,
        }

    @staticmethod
    def get_yoy_growth(db: Session, report_month: str) -> Dict[str, Any]:
        year, month = map(int, report_month.split("-"))
        last_year = year - 1
        last_month_str = f"{last_year:04d}-{month:02d}"

        current = ReportDataCollector.get_monthly_data(db, report_month)
        last_year_data = ReportDataCollector.get_monthly_data(db, last_month_str)

        def calc_growth(curr, prev):
            if prev == 0:
                return Decimal("0")
            return ((Decimal(curr) - Decimal(prev)) / Decimal(prev)) * 100

        return {
            "yoy_grants_growth": calc_growth(
                current["total_grants_shares"],
                last_year_data["total_grants_shares"],
            ),
            "yoy_exercises_growth": calc_growth(
                current["total_exercises_shares"],
                last_year_data["total_exercises_shares"],
            ),
            "yoy_repurchases_growth": calc_growth(
                current["total_repurchases_shares"],
                last_year_data["total_repurchases_shares"],
            ),
            "current_month": current,
            "last_year_month": last_year_data,
        }

    @staticmethod
    def get_trend_data(db: Session, months: int = 12) -> Dict[str, Any]:
        today = date.today()
        trend = []

        for i in range(months - 1, -1, -1):
            if today.month - i <= 0:
                y = today.year - 1
                m = today.month - i + 12
            else:
                y = today.year
                m = today.month - i

            month_str = f"{y:04d}-{m:02d}"
            data = ReportDataCollector.get_monthly_data(db, month_str)
            trend.append({
                "month": month_str,
                "grants_shares": data["total_grants_shares"],
                "exercises_shares": data["total_exercises_shares"],
                "repurchases_shares": data["total_repurchases_shares"],
            })

        return {
            "months": months,
            "trend_data": trend,
        }


class ReportChartGenerator:
    @staticmethod
    def generate_trend_chart(trend_data: List[Dict[str, Any]], output_path: str) -> str:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.font_manager as fm

            plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False

            months = [d["month"] for d in trend_data]
            grants = [d["grants_shares"] for d in trend_data]
            exercises = [d["exercises_shares"] for d in trend_data]
            repurchases = [d["repurchases_shares"] for d in trend_data]

            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

            x = range(len(months))

            ax1.bar(x, grants, alpha=0.6, label="授予量", color="#4CAF50")
            ax1.set_title("月度股权授予量趋势")
            ax1.set_xlabel("月份")
            ax1.set_ylabel("股份数量")
            ax1.set_xticks(x)
            ax1.set_xticklabels(months, rotation=45)
            ax1.legend()
            ax1.grid(axis="y", alpha=0.3)

            for i, v in enumerate(grants):
                ax1.text(i, v, f"{v:,}", ha="center", va="bottom", fontsize=8)

            ax2.plot(x, exercises, marker="o", label="行权量", color="#2196F3", linewidth=2)
            ax2.plot(x, repurchases, marker="s", label="回购量", color="#F44336", linewidth=2)
            ax2.set_title("月度行权量与回购量趋势")
            ax2.set_xlabel("月份")
            ax2.set_ylabel("股份数量")
            ax2.set_xticks(x)
            ax2.set_xticklabels(months, rotation=45)
            ax2.legend()
            ax2.grid(alpha=0.3)

            plt.tight_layout()
            plt.savefig(output_path, dpi=150, bbox_inches="tight")
            plt.close()

            return output_path
        except Exception as e:
            logger.error(f"生成趋势图表失败: {e}")
            return ""


class PDFReportGenerator:
    @staticmethod
    def generate_pdf_report(report_data: Dict[str, Any], trend_image_path: str, output_path: str) -> str:
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib import colors
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
            )
            from reportlab.lib.units import inch

            doc = SimpleDocTemplate(
                output_path,
                pagesize=A4,
                rightMargin=0.75 * inch,
                leftMargin=0.75 * inch,
                topMargin=1 * inch,
                bottomMargin=1 * inch,
            )

            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                "CustomTitle",
                parent=styles["Title"],
                fontSize=24,
                spaceAfter=20,
                textColor=colors.HexColor("#1a1a2e"),
            )
            h2_style = ParagraphStyle(
                "H2",
                parent=styles["Heading2"],
                fontSize=16,
                spaceBefore=15,
                spaceAfter=10,
                textColor=colors.HexColor("#16213e"),
            )
            normal_style = styles["Normal"]

            story = []

            story.append(Paragraph("员工股权激励月度综合分析报告", title_style))
            story.append(Paragraph(
                f"报告期: {report_data['report_month']} | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                ParagraphStyle("Subtitle", parent=normal_style, fontSize=10, textColor=colors.gray, alignment=1)
            ))
            story.append(Spacer(1, 20))

            story.append(Paragraph("一、核心指标概览", h2_style))

            overview_data = [
                ["指标", "数值", "同比变化"],
                ["授予数量", f"{report_data['total_grants_shares']:,} 股", f"{float(report_data.get('yoy_grants_growth', 0)):.2f}%"],
                ["行权数量", f"{report_data['total_exercises_shares']:,} 股", f"{float(report_data.get('yoy_exercises_growth', 0)):.2f}%"],
                ["回购数量", f"{report_data['total_repurchases_shares']:,} 股", f"{float(report_data.get('yoy_repurchases_growth', 0)):.2f}%"],
                ["库存股份", f"{report_data['inventory_shares']:,} 股", "-"],
                ["已发行未归属", f"{report_data['outstanding_shares']:,} 股", "-"],
                ["已归属未行权", f"{report_data['vested_shares'] - report_data['exercised_shares']:,} 股", "-"],
                ["人均收益", f"¥ {float(report_data['average_profit_per_employee']):,.2f}", "-"],
            ]

            overview_table = Table(overview_data, colWidths=[2.5 * inch, 2 * inch, 1.5 * inch])
            overview_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16213e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 11),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.HexColor("#f0f0f0")]),
            ]))
            story.append(overview_table)

            story.append(Spacer(1, 30))

            story.append(Paragraph("二、授予与行权统计", h2_style))
            detail_data = [
                ["类别", "笔数", "股份数"],
                ["股权授予", f"{report_data['total_grants_count']}", f"{report_data['total_grants_shares']:,}"],
                ["行权申请", f"{report_data['total_exercises_count']}", f"{report_data['total_exercises_shares']:,}"],
                ["股权回购", f"{report_data['total_repurchases_count']}", f"{report_data['total_repurchases_shares']:,}"],
            ]
            detail_table = Table(detail_data, colWidths=[2 * inch, 2 * inch, 2 * inch])
            detail_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f3460")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 1, colors.gray),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.HexColor("#e8f4f8")]),
            ]))
            story.append(detail_table)

            if trend_image_path and Path(trend_image_path).exists():
                story.append(Spacer(1, 20))
                story.append(Paragraph("三、同比趋势分析", h2_style))
                img = Image(trend_image_path, width=6.5 * inch, height=4.5 * inch)
                story.append(img)

            story.append(Spacer(1, 30))
            story.append(Paragraph(
                "报告生成: 示例科技 - 股权激励管理系统 | 本报告仅供内部参考",
                ParagraphStyle("Footer", parent=normal_style, fontSize=8, textColor=colors.gray, alignment=1)
            ))

            doc.build(story)
            return output_path
        except Exception as e:
            logger.error(f"生成PDF报告失败: {e}", exc_info=True)
            return ""


class ExcelReportGenerator:
    @staticmethod
    def generate_excel_report(report_data: Dict[str, Any], trend_data: List[Dict[str, Any]], output_path: str) -> str:
        try:
            import pandas as pd

            with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
                overview_df = pd.DataFrame([
                    {"指标": "授予数量（股）", "数值": report_data["total_grants_shares"], "同比": float(report_data.get("yoy_grants_growth", 0))},
                    {"指标": "行权数量（股）", "数值": report_data["total_exercises_shares"], "同比": float(report_data.get("yoy_exercises_growth", 0))},
                    {"指标": "回购数量（股）", "数值": report_data["total_repurchases_shares"], "同比": float(report_data.get("yoy_repurchases_growth", 0))},
                    {"指标": "授予笔数", "数值": report_data["total_grants_count"], "同比": "-"},
                    {"指标": "行权笔数", "数值": report_data["total_exercises_count"], "同比": "-"},
                    {"指标": "回购笔数", "数值": report_data["total_repurchases_count"], "同比": "-"},
                    {"指标": "库存股份（股）", "数值": report_data["inventory_shares"], "同比": "-"},
                    {"指标": "已发行未归属（股）", "数值": report_data["outstanding_shares"], "同比": "-"},
                    {"指标": "已归属股份（股）", "数值": report_data["vested_shares"], "同比": "-"},
                    {"指标": "已行权股份（股）", "数值": report_data["exercised_shares"], "同比": "-"},
                    {"指标": "活跃员工数", "数值": report_data["active_employees"], "同比": "-"},
                    {"指标": "人均行权收益（元）", "数值": float(report_data["average_profit_per_employee"]), "同比": "-"},
                ])
                overview_df.to_excel(writer, sheet_name="核心指标概览", index=False)

                trend_df = pd.DataFrame(trend_data)
                trend_df.columns = ["月份", "授予量(股)", "行权量(股)", "回购量(股)"]
                trend_df.to_excel(writer, sheet_name="趋势数据", index=False)

                detail_df = pd.DataFrame([
                    {"类别": "股权授予", "笔数": report_data["total_grants_count"], "股份数": report_data["total_grants_shares"]},
                    {"类别": "行权申请", "笔数": report_data["total_exercises_count"], "股份数": report_data["total_exercises_shares"]},
                    {"类别": "股权回购", "笔数": report_data["total_repurchases_count"], "股份数": report_data["total_repurchases_shares"]},
                ])
                detail_df.to_excel(writer, sheet_name="分类明细", index=False)

            return output_path
        except Exception as e:
            logger.error(f"生成Excel报告失败: {e}", exc_info=True)
            return ""


class MonthlyReportService:
    @staticmethod
    def _ensure_dir() -> None:
        Path(settings.report_output_dir).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def generate_monthly_report(
        db: Session,
        report_month: Optional[str] = None,
        operator_id: str = "system",
    ) -> MonthlyReport:
        MonthlyReportService._ensure_dir()

        if report_month is None:
            today = date.today()
            report_month = f"{today.year:04d}-{today.month:02d}"

        existing = (
            db.query(MonthlyReport)
            .filter(MonthlyReport.report_month == report_month)
            .first()
        )
        if existing and existing.is_generated:
            logger.info(f"报告已存在: {report_month}")
            return existing

        data = ReportDataCollector.get_monthly_data(db, report_month)
        yoy = ReportDataCollector.get_yoy_growth(db, report_month)
        trend = ReportDataCollector.get_trend_data(db, 12)

        report_data = {**data, **yoy}

        chart_path = f"{settings.report_output_dir}/trend_{report_month}.png"
        ReportChartGenerator.generate_trend_chart(trend["trend_data"], chart_path)

        pdf_path = f"{settings.report_output_dir}/equity_report_{report_month}.pdf"
        PDFReportGenerator.generate_pdf_report(report_data, chart_path, pdf_path)

        excel_path = f"{settings.report_output_dir}/equity_report_{report_month}.xlsx"
        ExcelReportGenerator.generate_excel_report(report_data, trend["trend_data"], excel_path)

        if existing:
            report = existing
        else:
            report = MonthlyReport(report_id=generate_id("RPT"), report_month=report_month)
            db.add(report)

        report.total_grants_count = data["total_grants_count"]
        report.total_grants_shares = data["total_grants_shares"]
        report.total_exercises_count = data["total_exercises_count"]
        report.total_exercises_shares = data["total_exercises_shares"]
        report.total_repurchases_count = data["total_repurchases_count"]
        report.total_repurchases_shares = data["total_repurchases_shares"]
        report.inventory_shares = data["inventory_shares"]
        report.outstanding_shares = data["outstanding_shares"]
        report.vested_shares = data["vested_shares"]
        report.average_profit_per_employee = data["average_profit_per_employee"]
        report.yoy_grants_growth = yoy["yoy_grants_growth"]
        report.yoy_exercises_growth = yoy["yoy_exercises_growth"]
        report.yoy_repurchases_growth = yoy["yoy_repurchases_growth"]
        report.summary_data = report_data
        report.chart_data = trend
        report.pdf_path = pdf_path if Path(pdf_path).exists() else None
        report.excel_path = excel_path if Path(excel_path).exists() else None
        report.is_generated = True
        report.generated_at = datetime.utcnow()

        db.flush()

        OperationLogger.log(
            db=db,
            action=LogAction.GENERATE,
            resource_type="monthly_report",
            resource_id=report.report_id,
            operator_id=operator_id,
            description=f"生成月度股权报告: {report_month}",
        )

        db.commit()
        db.refresh(report)
        logger.info(f"月度报告生成完成: {report_month}")
        return report

    @staticmethod
    def get_report(db: Session, report_month: str) -> Optional[MonthlyReport]:
        return (
            db.query(MonthlyReport)
            .filter(MonthlyReport.report_month == report_month)
            .first()
        )

    @staticmethod
    def list_reports(db: Session, skip: int = 0, limit: int = 24) -> List[MonthlyReport]:
        return (
            db.query(MonthlyReport)
            .order_by(MonthlyReport.report_month.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
