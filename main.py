from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler

from config import settings
from database import init_db
from utils.logger import setup_logging, get_logger
from api import api_router

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info(f"启动 {settings.app_name} 服务...")
    init_db()
    logger.info("数据库初始化完成")

    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    try:
        from apscheduler.triggers.cron import CronTrigger
        from tasks import (
            hr_sync_task,
            process_vesting_task,
            generate_monthly_report_task,
            executive_monitoring_task,
            shareholder_update_task,
        )

        scheduler.add_job(
            lambda: hr_sync_task.delay(),
            CronTrigger(minute=0),
            id="hr_sync",
            name="HR系统同步",
            replace_existing=True,
        )
        logger.info("已注册定时任务: HR系统同步 (每小时)")

        scheduler.add_job(
            lambda: process_vesting_task.delay(),
            CronTrigger(hour=2, minute=0),
            id="process_vesting",
            name="每日归属处理",
            replace_existing=True,
        )
        logger.info("已注册定时任务: 每日归属处理 (凌晨2点)")

        scheduler.add_job(
            lambda: generate_monthly_report_task.delay(),
            CronTrigger(day=1, hour=3, minute=0),
            id="monthly_report",
            name="月度报告生成",
            replace_existing=True,
        )
        logger.info("已注册定时任务: 月度报告生成 (每月1号凌晨3点)")

        scheduler.add_job(
            lambda: executive_monitoring_task.delay(),
            CronTrigger(hour=9, minute=0),
            id="executive_monitoring",
            name="高管持仓监控",
            replace_existing=True,
        )
        logger.info("已注册定时任务: 高管持仓监控 (每天上午9点)")

        scheduler.add_job(
            lambda: shareholder_update_task.delay(),
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
