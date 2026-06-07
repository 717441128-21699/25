from celery import Celery
from celery.schedules import crontab
from config import settings

celery_app = Celery(
    "equity_tasks",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_queues={
        "default": {
            "exchange": "default",
            "routing_key": "default",
        },
        "hr_sync": {
            "exchange": "hr_sync",
            "routing_key": "hr_sync",
        },
        "exercise": {
            "exchange": "exercise",
            "routing_key": "exercise",
        },
        "report": {
            "exchange": "report",
            "routing_key": "report",
        },
    },
    beat_schedule={
        "hr-sync-every-hour": {
            "task": "tasks.hr_sync_task",
            "schedule": crontab(minute=0),
            "options": {"queue": "hr_sync"},
        },
        "daily-vesting-process": {
            "task": "tasks.process_vesting_task",
            "schedule": crontab(hour=2, minute=0),
        },
        "monthly-report-generation": {
            "task": "tasks.generate_monthly_report_task",
            "schedule": crontab(day_of_month=1, hour=3, minute=0),
            "options": {"queue": "report"},
        },
        "daily-executive-monitoring": {
            "task": "tasks.executive_monitoring_task",
            "schedule": crontab(hour=9, minute=0),
        },
        "daily-shareholder-update": {
            "task": "tasks.shareholder_update_task",
            "schedule": crontab(hour=1, minute=0),
        },
    },
)


@celery_app.task(name="tasks.hr_sync_task", bind=True, max_retries=3)
def hr_sync_task(self):
    from database import SessionLocal
    from services import EmployeeSyncService
    from utils.logger import get_logger

    logger = get_logger("celery_hr_sync")
    db = SessionLocal()
    try:
        result = EmployeeSyncService.sync_all_employees(db)
        logger.info(f"HR同步任务完成: {result}")
        return result
    except Exception as e:
        logger.error(f"HR同步任务失败: {e}", exc_info=True)
        self.retry(exc=e, countdown=60)
    finally:
        db.close()


@celery_app.task(name="tasks.process_vesting_task", bind=True)
def process_vesting_task(self):
    from database import SessionLocal
    from services import GrantService
    from utils.logger import get_logger

    logger = get_logger("celery_vesting")
    db = SessionLocal()
    try:
        result = GrantService.process_vesting(db)
        logger.info(f"归属处理任务完成: {result}")
        return result
    except Exception as e:
        logger.error(f"归属处理任务失败: {e}", exc_info=True)
        self.retry(exc=e, countdown=300)
    finally:
        db.close()


@celery_app.task(name="tasks.generate_monthly_report_task", bind=True, max_retries=2)
def generate_monthly_report_task(self, report_month=None):
    from database import SessionLocal
    from services import MonthlyReportService
    from utils.logger import get_logger

    logger = get_logger("celery_report")
    db = SessionLocal()
    try:
        report = MonthlyReportService.generate_monthly_report(db, report_month)
        logger.info(f"月度报告生成完成: {report.report_month}")
        return {"report_id": report.report_id, "report_month": report.report_month}
    except Exception as e:
        logger.error(f"月度报告生成失败: {e}", exc_info=True)
        self.retry(exc=e, countdown=600)
    finally:
        db.close()


@celery_app.task(name="tasks.executive_monitoring_task", bind=True)
def executive_monitoring_task(self):
    from database import SessionLocal
    from services import ExecutiveMonitoringService
    from utils.logger import get_logger

    logger = get_logger("celery_exec_monitor")
    db = SessionLocal()
    try:
        alerts = ExecutiveMonitoringService.monitor_all_executives(db)
        logger.info(f"高管监控完成: 发现 {len(alerts)} 项预警")
        return {"alerts_count": len(alerts), "alerts": alerts}
    except Exception as e:
        logger.error(f"高管监控失败: {e}", exc_info=True)
    finally:
        db.close()


@celery_app.task(name="tasks.shareholder_update_task", bind=True)
def shareholder_update_task(self):
    from database import SessionLocal
    from services import ShareholderService
    from utils.logger import get_logger

    logger = get_logger("celery_shareholder")
    db = SessionLocal()
    try:
        result = ShareholderService.bulk_update_all(db)
        logger.info(f"股东名册更新完成: {result}")
        return result
    except Exception as e:
        logger.error(f"股东名册更新失败: {e}", exc_info=True)
    finally:
        db.close()


@celery_app.task(name="tasks.bulk_exercise_task", bind=True)
def bulk_exercise_task(self, request_ids):
    from database import SessionLocal
    from services import ExerciseService
    from utils.logger import get_logger

    logger = get_logger("celery_exercise")
    db = SessionLocal()
    try:
        result = ExerciseService.bulk_process_exercises(db, request_ids)
        logger.info(f"批量行权完成: {result}")
        return result
    except Exception as e:
        logger.error(f"批量行权失败: {e}", exc_info=True)
    finally:
        db.close()


@celery_app.task(name="tasks.generate_agreement_task", bind=True)
def generate_agreement_task(self, grant_id: int):
    from database import SessionLocal
    from database.models import EquityGrant
    from services import AgreementService
    from utils.logger import get_logger

    logger = get_logger("celery_agreement")
    db = SessionLocal()
    try:
        grant = db.query(EquityGrant).filter(EquityGrant.id == grant_id).first()
        if grant:
            agreement = AgreementService.generate_grant_agreement(db, grant)
            AgreementService.send_agreement(db, agreement.agreement_id)
            logger.info(f"协议生成并发送: {agreement.agreement_id}")
            return {"agreement_id": agreement.agreement_id}
        return {"error": "Grant not found"}
    except Exception as e:
        logger.error(f"协议生成失败: {e}", exc_info=True)
    finally:
        db.close()
