from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from decimal import Decimal
from datetime import date, datetime
import json

from config import settings
from database import init_db
from utils.logger import setup_logging, get_logger
from api import api_router

logger = get_logger("main")


def _json_default(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except Exception:
            return list(obj)
    if isinstance(obj, set):
        return list(obj)
    if hasattr(obj, "value"):
        try:
            return obj.value
        except Exception:
            pass
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class CustomJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(
            jsonable_encoder(content, custom_encoder={
                Decimal: lambda v: str(v),
                datetime: lambda v: v.isoformat(),
                date: lambda v: v.isoformat(),
            }),
            ensure_ascii=False,
            default=_json_default,
        ).encode("utf-8")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info(f"启动 {settings.app_name} 服务...")
    init_db()
    logger.info("数据库初始化完成")

    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    try:
        from apscheduler.triggers.cron import CronTrigger
        from database import SessionLocal
        from services import (
            EmployeeSyncService,
            GrantService,
            MonthlyReportService,
            ExecutiveMonitoringService,
            ShareholderService,
        )

        def _run_hr_sync():
            db = SessionLocal()
            try:
                result = EmployeeSyncService.sync_all_employees(db)
                logger.info(f"[定时任务] HR系统同步完成: {result}")
            except Exception as e:
                logger.error(f"[定时任务] HR系统同步失败: {e}", exc_info=True)
            finally:
                db.close()

        def _run_vesting():
            db = SessionLocal()
            try:
                result = GrantService.process_vesting(db)
                logger.info(f"[定时任务] 每日归属处理完成: {result}")
            except Exception as e:
                logger.error(f"[定时任务] 每日归属处理失败: {e}", exc_info=True)
            finally:
                db.close()

        def _run_monthly_report():
            db = SessionLocal()
            try:
                report = MonthlyReportService.generate_monthly_report(db)
                logger.info(f"[定时任务] 月度报告生成完成: {report.report_month}")
            except Exception as e:
                logger.error(f"[定时任务] 月度报告生成失败: {e}", exc_info=True)
            finally:
                db.close()

        def _run_exec_monitor():
            db = SessionLocal()
            try:
                alerts = ExecutiveMonitoringService.monitor_all_executives(db)
                logger.info(f"[定时任务] 高管持仓监控完成: 发现 {len(alerts)} 项预警")
            except Exception as e:
                logger.error(f"[定时任务] 高管持仓监控失败: {e}", exc_info=True)
            finally:
                db.close()

        def _run_shareholder():
            db = SessionLocal()
            try:
                result = ShareholderService.bulk_update_all(db)
                logger.info(f"[定时任务] 股东名册更新完成: {result}")
            except Exception as e:
                logger.error(f"[定时任务] 股东名册更新失败: {e}", exc_info=True)
            finally:
                db.close()

        scheduler.add_job(
            _run_hr_sync,
            CronTrigger(minute=0),
            id="hr_sync",
            name="HR系统同步",
            replace_existing=True,
        )
        logger.info("已注册定时任务: HR系统同步 (每小时)")

        scheduler.add_job(
            _run_vesting,
            CronTrigger(hour=2, minute=0),
            id="process_vesting",
            name="每日归属处理",
            replace_existing=True,
        )
        logger.info("已注册定时任务: 每日归属处理 (凌晨2点)")

        scheduler.add_job(
            _run_monthly_report,
            CronTrigger(day=1, hour=3, minute=0),
            id="monthly_report",
            name="月度报告生成",
            replace_existing=True,
        )
        logger.info("已注册定时任务: 月度报告生成 (每月1号凌晨3点)")

        scheduler.add_job(
            _run_exec_monitor,
            CronTrigger(hour=9, minute=0),
            id="executive_monitoring",
            name="高管持仓监控",
            replace_existing=True,
        )
        logger.info("已注册定时任务: 高管持仓监控 (每天上午9点)")

        scheduler.add_job(
            _run_shareholder,
            CronTrigger(hour=1, minute=0),
            id="shareholder_update",
            name="股东名册更新",
            replace_existing=True,
        )
        logger.info("已注册定时任务: 股东名册更新 (凌晨1点)")

        scheduler.start()
        logger.info("定时任务调度器已启动")
    except Exception as e:
        logger.warning(f"定时任务启动失败: {e}")

    yield

    scheduler.shutdown()
    logger.info("定时任务调度器已停止")
    logger.info(f"{settings.app_name} 服务已停止")


app = FastAPI(
    title=settings.app_name,
    description="企业级员工股权激励自动化管理系统",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    default_response_class=CustomJSONResponse,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["系统"])
async def health_check():
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": "1.0.0",
        "environment": settings.app_env,
    }


@app.get("/", tags=["系统"])
async def root():
    return {
        "message": "员工股权激励自动化管理系统 API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"全局异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "服务器内部错误",
            "error": str(exc) if settings.debug else None,
        },
    )


app.include_router(api_router)
