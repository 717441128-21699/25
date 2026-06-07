import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import init_db, SessionLocal
from database.models import (
    EquityPlan, EquityType, Employee, EmployeeLevel, StockPrice,
    EquityGrant, VestingStatus,
)
from services import (
    EmployeeSyncService, EquityPlanService, GrantService,
    ShareholderService,
)
from utils.logger import setup_logging, get_logger
from datetime import date
from decimal import Decimal
import random

setup_logging()
logger = get_logger("init_data")


def _generate_mock_employees(db) -> int:
    from database.models import Employee, EmployeeLevel
    logger.info("创建示例员工数据（Mock模式）...")

    levels = list(EmployeeLevel)
    departments = ["技术部", "产品部", "市场部", "销售部", "财务部", "人力资源部", "法务部", "运营部"]
    positions_by_level = {
        EmployeeLevel.STAFF: ["软件工程师", "产品专员", "市场专员", "销售代表", "会计"],
        EmployeeLevel.MANAGER: ["项目经理", "产品经理", "市场经理", "销售经理", "财务主管"],
        EmployeeLevel.DIRECTOR: ["研发总监", "产品总监", "市场总监", "销售总监", "财务总监"],
        EmployeeLevel.VP: ["技术VP", "产品VP", "销售VP", "运营VP"],
        EmployeeLevel.C_LEVEL: ["CEO", "CTO", "CFO", "COO", "CMO"],
        EmployeeLevel.BOARD_MEMBER: ["董事长", "董事"],
    }

    count = 0
    try:
        existing = {e.employee_id for e in db.query(Employee).all()}

        for i in range(1, 201):
            emp_id = f"EMP{i:06d}"
            if emp_id in existing:
                continue

            level = levels[min(i // 35, len(levels) - 1)]
            positions = positions_by_level[level]
            department = departments[i % len(departments)]
            hire_year = 2018 + (i % 7)
            hire_month = (i % 12) + 1
            hire_day = (i % 28) + 1

            is_executive = level in [EmployeeLevel.C_LEVEL, EmployeeLevel.BOARD_MEMBER, EmployeeLevel.VP]

            db.add(Employee(
                employee_id=emp_id,
                name=f"员工{i}",
                email=f"employee{i}@company.com",
                phone=f"138{i:08d}",
                department=department,
                position=positions[i % len(positions)],
                level=level,
                is_executive=is_executive,
                hire_date=date(hire_year, hire_month, hire_day),
                termination_date=None,
                is_active=True,
                salary=Decimal((i + 1) * 5000),
                currency="CNY",
                country="中国",
                id_number=f"110101{hire_year:04d}{hire_month:02d}{hire_day:02d}{i:04d}",
                bank_account=f"622202{i:012d}",
                bank_name="中国工商银行",
                tax_id=f"TAX{i:010d}",
            ))
            count += 1

        db.commit()
        logger.info(f"已创建 {count} 名员工（Mock）")
    except Exception as e:
        db.rollback()
        logger.error(f"创建员工失败: {e}", exc_info=True)
    return count


def _generate_stock_prices(db) -> int:
    logger.info("创建历史股价数据（Mock模式）...")
    count = 0
    try:
        base_price = Decimal("85.50")
        from dateutil.relativedelta import relativedelta

        existing_dates = {sp.trade_date for sp in db.query(StockPrice).all()}

        for i in range(120):
            d = date.today()
            trade_date = d - relativedelta(days=i)
            if trade_date.weekday() >= 5:
                continue
            if trade_date in existing_dates:
                continue

            change = Decimal(random.uniform(-3, 3))
            price = base_price + change + (Decimal(i) * Decimal("0.02"))
            price = round(price, 2)
            db.add(StockPrice(
                trade_date=trade_date,
                price=price,
                open_price=round(price - Decimal(random.uniform(0, 2)), 2),
                high_price=round(price + Decimal(random.uniform(0, 3)), 2),
                low_price=round(price - Decimal(random.uniform(0, 3)), 2),
                close_price=price,
                volume=random.randint(100000, 1000000),
                currency="CNY",
                source="mock",
            ))
            count += 1

        db.commit()
        logger.info(f"已创建 {count} 条股价记录")
    except Exception as e:
        db.rollback()
        logger.error(f"创建股价失败: {e}", exc_info=True)
    return count


def seed_database():
    logger.info("=" * 60)
    logger.info("开始初始化数据库...")
    logger.info("=" * 60)

    try:
        init_db()
    except Exception as e:
        logger.warning(f"数据库表创建告警: {e}")

    db = SessionLocal()

    try:
        plan_count = db.query(EquityPlan).count()
        if plan_count == 0:
            logger.info("创建示例激励计划...")

            plans_data = [
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
                    "exercise_price_method": "FMV_GRANT_DATE",
                    "exercise_price_discount": Decimal("0.80"),
                },
            ]

            for p in plans_data:
                EquityPlanService.create_plan(db, p, operator_id="init")

            logger.info(f"已创建 {len(plans_data)} 个激励计划")
        else:
            logger.info(f"激励计划已存在: {plan_count} 个")

        emp_count = db.query(Employee).count()
        if emp_count == 0:
            _generate_mock_employees(db)
        else:
            logger.info(f"员工数据已存在: {emp_count} 人")

        price_count = db.query(StockPrice).count()
        if price_count < 30:
            _generate_stock_prices(db)
        else:
            logger.info(f"股价数据已存在: {price_count} 条")

        employees = db.query(Employee).filter(Employee.is_active == True).limit(30).all()
        plans = EquityPlanService.list_active_plans(db)
        grant_count = db.query(EquityGrant).count()

        if grant_count == 0 and employees and plans:
            logger.info(f"为 {len(employees)} 名员工创建股权授予...")
            created = 0
            for idx, emp in enumerate(employees):
                plan = plans[idx % len(plans)]
                try:
                    from dateutil.relativedelta import relativedelta
                    grant_date = date.today() - relativedelta(months=random.randint(3, 15))
                    grant = GrantService.create_grant(
                        db=db,
                        employee=emp,
                        plan=plan,
                        grant_date=grant_date,
                        operator_id="init",
                    )
                    grant.is_accepted = True
                    grant.acceptance_date = grant_date
                    created += 1
                except Exception as e:
                    logger.warning(f"为员工 {emp.employee_id} 创建授予失败: {e}")
            db.commit()
            logger.info(f"已创建 {created} 个股权授予")

            logger.info("处理股权归属...")
            try:
                GrantService.process_vesting(db)
            except Exception as e:
                logger.warning(f"处理归属时出错: {e}")
        elif grant_count > 0:
            logger.info(f"授予记录已存在: {grant_count} 条")

        logger.info("更新股东名册...")
        try:
            ShareholderService.bulk_update_all(db)
        except Exception as e:
            logger.warning(f"更新股东名册时出错: {e}")

        logger.info("=" * 60)
        logger.info("数据库初始化完成!")
        logger.info("  激励计划: %d 个", db.query(EquityPlan).count())
        logger.info("  员工总数: %d 人", db.query(Employee).count())
        logger.info("  股权授予: %d 条", db.query(EquityGrant).count())
        logger.info("  股价记录: %d 条", db.query(StockPrice).count())
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"初始化失败: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
