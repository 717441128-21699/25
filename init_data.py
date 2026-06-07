from database import init_db, SessionLocal
from database.models import (
    EquityPlan, EquityType, Employee, EmployeeLevel, StockPrice,
)
from services import (
    EmployeeSyncService, EquityPlanService, GrantService,
    MonthlyReportService, ShareholderService,
)
from utils.logger import setup_logging, get_logger
from datetime import date, datetime
from decimal import Decimal
import random

setup_logging()
logger = get_logger("init_data")


def seed_database():
    logger.info("初始化数据库...")
    init_db()
    db = SessionLocal()

    try:
        plan_count = db.query(EquityPlan).count()
        if plan_count == 0:
            logger.info("创建示例激励计划...")

            plans = [
                {
                    "plan_code": "OPT-2024",
                    "plan_name": "2024年度股票期权激励计划",
                    "equity_type": EquityType.OPTION,
                    "total_shares_reserved": 5000000,
                    "effective_date": date(2024, 1, 1),
                    "expiration_date": date(2034, 1, 1),
                    "vesting_period_months": 48,
                    "cliff_months": 12,
                    "vesting_interval_months": 3,
                    "cliff_percentage": Decimal("0.25"),
                    "exercise_price_method": "FMV_GRANT_DATE",
                    "exercise_price_discount": Decimal("1.0"),
                },
                {
                    "plan_code": "RSU-2024",
                    "plan_name": "2024年度限制性股票激励计划",
                    "equity_type": EquityType.RESTRICTED_STOCK,
                    "total_shares_reserved": 3000000,
                    "effective_date": date(2024, 1, 1),
                    "expiration_date": date(2029, 1, 1),
                    "vesting_period_months": 36,
                    "cliff_months": 12,
                    "vesting_interval_months": 6,
                    "cliff_percentage": Decimal("0.33"),
                    "exercise_price_method": "FIXED",
                    "min_exercise_price": Decimal("1.00"),
                },
                {
                    "plan_code": "PSU-2024",
                    "plan_name": "2024年度业绩股票激励计划",
                    "equity_type": EquityType.PERFORMANCE_STOCK,
                    "total_shares_reserved": 2000000,
                    "effective_date": date(2024, 1, 1),
                    "expiration_date": date(2027, 1, 1),
                    "vesting_period_months": 24,
                    "cliff_months": 12,
                    "vesting_interval_months": 12,
                    "cliff_percentage": Decimal("0.50"),
                    "exercise_price_method": "AVERAGE_30_DAYS",
                    "exercise_price_discount": Decimal("0.80"),
                    "performance_metrics": {
                        "revenue_growth": ">=20%",
                        "eps_growth": ">=15%",
                    },
                },
            ]

            for p in plans:
                EquityPlanService.create_plan(db, p, operator_id="init")

            logger.info(f"已创建 {len(plans)} 个激励计划")

        emp_count = db.query(Employee).count()
        if emp_count == 0:
            logger.info("创建示例员工数据...")
            import asyncio
            result = asyncio.run(EmployeeSyncService.sync_all_employees(db, operator_id="init"))
            logger.info(f"已同步 {result} 名员工")

        price_count = db.query(StockPrice).count()
        if price_count == 0:
            logger.info("创建历史股价数据...")
            base_price = Decimal("85.50")
            for i in range(365):
                d = date.today()
                from dateutil.relativedelta import relativedelta
                trade_date = d - relativedelta(days=i)
                if trade_date.weekday() < 5:
                    change = Decimal(random.uniform(-2, 2))
                    price = base_price + change + (Decimal(i) * Decimal("0.05"))
                    price = round(price, 2)
                    db.add(StockPrice(
                        trade_date=trade_date,
                        price=price,
                        open_price=price - Decimal(random.uniform(0, 2)),
                        high_price=price + Decimal(random.uniform(0, 3)),
                        low_price=price - Decimal(random.uniform(0, 3)),
                        close_price=price,
                        volume=random.randint(100000, 1000000),
                        currency="CNY",
                        source="mock",
                    ))
            db.commit()
            logger.info("已创建365天历史股价数据")

        employees = db.query(Employee).filter(Employee.is_active == True).limit(50).all()
        plans = EquityPlanService.list_active_plans(db)
        from database.models import EquityGrant

        grant_count = db.query(EquityGrant).count()
        if grant_count == 0 and employees and plans:
            logger.info("为示例员工创建股权授予...")
            created = 0
            for idx, emp in enumerate(employees):
                plan = plans[idx % len(plans)]
                try:
                    from dateutil.relativedelta import relativedelta
                    grant_date = date.today() - relativedelta(months=random.randint(1, 24))
                    grant = GrantService.create_grant(
                        db=db,
                        employee=emp,
                        plan=plan,
                        grant_date=grant_date,
                        operator_id="init",
                    )
                    created += 1
                except Exception as e:
                    logger.warning(f"为员工 {emp.employee_id} 创建授予失败: {e}")
            logger.info(f"已创建 {created} 个股权授予")

        logger.info("更新股东名册...")
        ShareholderService.bulk_update_all(db)

        logger.info("数据库初始化完成!")

    except Exception as e:
        logger.error(f"初始化失败: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
