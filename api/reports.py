from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import date as date_type
from typing import Optional
from io import BytesIO

from database import get_db
from database.models import MonthlyReport
from services import ReportService
from schemas import (
    MonthlyReportSchema, APIResponse, PaginatedResponse,
)
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/reports", tags=["报告中心"])
logger = get_logger("api_reports")


@router.post("/generate", response_model=APIResponse)
@router.post("", response_model=APIResponse)
def generate_monthly_report(
    report_date: Optional[str] = Query(None, description="报告月份 YYYY-MM"),
    db: Session = Depends(get_db),
):
    try:
        from datetime import datetime
        if report_date:
            try:
                parsed = datetime.strptime(report_date, "%Y-%m").date()
            except ValueError:
                parsed = date_type.today().replace(day=1)
        else:
            parsed = date_type.today().replace(day=1)

        report = ReportService.generate_monthly_report(db, parsed.year, parsed.month)
        return APIResponse(
            data=MonthlyReportSchema.model_validate(report).model_dump(),
            message=f"月度报告生成成功: {report.year}年{report.month}月",
        )
    except Exception as e:
        logger.error(f"生成月度报告失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=PaginatedResponse)
def list_reports(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(MonthlyReport)
    if year:
        query = query.filter(MonthlyReport.year == year)
    if month:
        query = query.filter(MonthlyReport.month == month)
    total = query.count()
    reports = query.order_by(MonthlyReport.year.desc(), MonthlyReport.month.desc()).offset(skip).limit(limit).all()
    return PaginatedResponse(
        data=[MonthlyReportSchema.model_validate(r).model_dump() for r in reports],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{report_id}", response_model=APIResponse)
def get_report(report_id: int, db: Session = Depends(get_db)):
    report = db.query(MonthlyReport).filter(MonthlyReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail=f"报告不存在: {report_id}")
    data = MonthlyReportSchema.model_validate(report).model_dump()
    try:
        import json
        if report.summary_data:
            data["summary"] = json.loads(report.summary_data) if isinstance(report.summary_data, str) else report.summary_data
    except Exception:
        pass
    return APIResponse(data=data)


@router.get("/{report_id}/pdf")
def download_report_pdf(report_id: int, db: Session = Depends(get_db)):
    report = db.query(MonthlyReport).filter(MonthlyReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail=f"报告不存在: {report_id}")

    try:
        pdf_bytes = ReportService.export_pdf(db, report)
        buffer = BytesIO(pdf_bytes)
        filename = f"monthly_report_{report.year}_{report.month:02d}.pdf"
        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.warning(f"PDF导出失败，降级为文本: {e}")
        try:
            import json
            summary = json.loads(report.summary_data) if isinstance(report.summary_data, str) else {}
        except Exception:
            summary = {"raw": str(report.summary_data)}
        lines = [
            f"股权激励月度报告",
            f"报告期间: {report.year}年{report.month}月",
            f"生成时间: {report.created_at}",
            "",
            "=== 核心指标 ===",
        ]
        if isinstance(summary, dict):
            for k, v in summary.items():
                if isinstance(v, (dict, list)):
                    try:
                        lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
                    except Exception:
                        lines.append(f"{k}: {v}")
                else:
                    lines.append(f"{k}: {v}")
        text = "\n".join(lines)
        buffer = BytesIO(text.encode("utf-8"))
        return StreamingResponse(
            buffer,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="monthly_report_{report.year}_{report.month:02d}.txt"'},
        )


@router.get("/{report_id}/excel")
def download_report_excel(report_id: int, db: Session = Depends(get_db)):
    report = db.query(MonthlyReport).filter(MonthlyReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail=f"报告不存在: {report_id}")

    try:
        excel_bytes = ReportService.export_excel(db, report)
        buffer = BytesIO(excel_bytes)
        filename = f"monthly_report_{report.year}_{report.month:02d}.xlsx"
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.warning(f"Excel导出失败，降级为CSV: {e}")
        try:
            import json, csv
            summary = json.loads(report.summary_data) if isinstance(report.summary_data, str) else {}
            output = BytesIO()
            writer = csv.writer(output)
            writer.writerow(["指标", "值"])
            if isinstance(summary, dict):
                for k, v in summary.items():
                    writer.writerow([k, str(v)])
            output.seek(0)
            return StreamingResponse(
                output,
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="monthly_report_{report.year}_{report.month:02d}.csv"'},
            )
        except Exception as e2:
            raise HTTPException(status_code=500, detail=f"Excel导出失败: {e}, {e2}")


@router.get("/current/summary", response_model=APIResponse)
def get_current_summary(db: Session = Depends(get_db)):
    from datetime import date
    today = date.today()
    report = ReportService.generate_monthly_report(db, today.year, today.month)
    return APIResponse(data=MonthlyReportSchema.model_validate(report).model_dump())
