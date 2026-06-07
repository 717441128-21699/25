from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import Optional
from pathlib import Path

from database import get_db
from services import MonthlyReportService
from schemas import MonthlyReportSchema, APIResponse, PaginatedResponse
from utils.logger import get_logger
from tasks import generate_monthly_report_task

router = APIRouter(prefix="/api/v1/reports", tags=["报告管理"])
logger = get_logger("api_report")


@router.post("/generate", response_model=APIResponse)
def generate_report(
    report_month: Optional[str] = None,
    async_mode: bool = True,
    db: Session = Depends(get_db),
):
    try:
        if async_mode:
            task = generate_monthly_report_task.delay(report_month)
            return APIResponse(
                data={"task_id": task.id, "report_month": report_month},
                message="报告生成任务已提交后台处理",
            )
        else:
            report = MonthlyReportService.generate_monthly_report(db, report_month)
            return APIResponse(
                data=MonthlyReportSchema.model_validate(report).model_dump(),
                message="月度报告已生成",
            )
    except Exception as e:
        logger.error(f"生成报告失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=PaginatedResponse)
def list_reports(
    skip: int = 0,
    limit: int = 24,
    db: Session = Depends(get_db),
):
    reports = MonthlyReportService.list_reports(db, skip, limit)
    return PaginatedResponse(
        data=[MonthlyReportSchema.model_validate(r).model_dump() for r in reports],
        total=len(reports),
        skip=skip,
        limit=limit,
    )


@router.get("/{report_month}", response_model=APIResponse)
def get_report(report_month: str, db: Session = Depends(get_db)):
    report = MonthlyReportService.get_report(db, report_month)
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    data = MonthlyReportSchema.model_validate(report).model_dump()
    if report.summary_data:
        data["summary"] = report.summary_data
    if report.chart_data:
        data["charts"] = report.chart_data
    return APIResponse(data=data)


@router.get("/{report_month}/download/pdf")
def download_report_pdf(report_month: str, db: Session = Depends(get_db)):
    report = MonthlyReportService.get_report(db, report_month)
    if not report or not report.pdf_path:
        raise HTTPException(status_code=404, detail="PDF报告不存在")

    pdf_path = Path(report.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF文件不存在")

    return FileResponse(
        path=pdf_path,
        filename=f"EquityReport_{report_month}.pdf",
        media_type="application/pdf",
    )


@router.get("/{report_month}/download/excel")
def download_report_excel(report_month: str, db: Session = Depends(get_db)):
    report = MonthlyReportService.get_report(db, report_month)
    if not report or not report.excel_path:
        raise HTTPException(status_code=404, detail="Excel报告不存在")

    excel_path = Path(report.excel_path)
    if not excel_path.exists():
        raise HTTPException(status_code=404, detail="Excel文件不存在")

    return FileResponse(
        path=excel_path,
        filename=f"EquityReport_{report_month}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
