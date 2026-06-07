from typing import Dict, Any, Optional, List
from datetime import date, datetime
from decimal import Decimal
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session
from database.models import (
    EquityPlan, EquityGrant, VestingSchedule, EquityType,
    Employee, EmployeeLevel, VestingStatus, StockPrice
)
from utils.common import generate_id, safe_decimal, safe_int
from utils.logger import get_logger
from utils.cache import redis_manager

logger = get_logger("equity_engine")


class StockPriceService:
    @staticmethod
    def get_current_price(db: Session, currency: str = "CNY") -> Decimal:
        cache_key = f"stock_price:{currency}:current"
        cached = redis_manager.get(cache_key)
        if cached:
            return Decimal(cached)

        latest = (
            db.query(StockPrice)
            .filter(StockPrice.currency == currency)
            .order_by(StockPrice.trade_date.desc())
            .first()
        )

        if latest:
            price = latest.price
            redis_manager.set(cache_key, str(price), ex=300)
            return price

        default_price = Decimal("100.00")
        logger.warning(f"未获取到股价，使用默认价格: {default_price}")
        return default_price

    @staticmethod
    def get_price_on_date(db: Session, target_date: date, currency: str = "CNY") -> Optional[Decimal]:
        cache_key = f"stock_price:{currency}:{target_date.isoformat()}"
        cached = redis_manager.get(cache_key)
        if cached:
            return Decimal(cached)

        price_record = (
            db.query(StockPrice)
            .filter(
                StockPrice.trade_date <= target_date,
                StockPrice.currency == currency,
            )
            .order_by(StockPrice.trade_date.desc())
            .first()
        )

        if price_record:
            redis_manager.set(cache_key, str(price_record.price), ex=86400)
            return price_record.price

        return None

    @staticmethod
    def calculate_grant_price(
        db: Session,
        plan: EquityPlan,
        grant_date: date,
    ) -> Decimal:
        if plan.exercise_price_method == "FIXED":
            return safe_decimal(plan.min_exercise_price, Decimal("0"))

        if plan.exercise_price_method == "FMV_GRANT_DATE":
            price = StockPriceService.get_price_on_date(db, grant_date)
            if price:
                result = price * safe_decimal(plan.exercise_price_discount, Decimal("1.0"))
                if plan.min_exercise_price:
                    return max(result, safe_decimal(plan.min_exercise_price))
                return result

        if plan.exercise_price_method == "AVERAGE_30_DAYS":
            total = Decimal("0")
            count = 0
            for i in range(30):
                d = grant_date - relativedelta(days=i)
                p = StockPriceService.get_price_on_date(db, d)
                if p:
                    total += p
                    count += 1
            if count > 0:
                avg = total / count
                result = avg * safe_decimal(plan.exercise_price_discount, Decimal("1.0"))
                if plan.min_exercise_price:
                    return max(result, safe_decimal(plan.min_exercise_price))
                return result

        current = StockPriceService.get_current_price(db)
        return current * safe_decimal(plan.exercise_price_discount, Decimal("1.0"))


class VestingScheduleGenerator:
    @staticmethod
    def generate_schedule(
        grant: EquityGrant,
        plan: EquityPlan,
    ) -> List[VestingSchedule]:
        schedules = []
        total_shares = grant.total_shares
        start_date = grant.vesting_start_date
        cliff_months = plan.cliff_months
        vesting_period = plan.vesting_period_months
        interval_months = plan.vesting_interval_months
        cliff_pct = safe_decimal(plan.cliff_percentage, Decimal("0.25"))

        cliff_date = start_date + relativedelta(months=cliff_months)
        cliff_shares = int(total_shares * cliff_pct)

        if cliff_shares > 0:
            schedules.append(VestingSchedule(
                grant_id=grant.id,
                vesting_date=cliff_date,
                scheduled_shares=cliff_shares,
                status=VestingStatus.PENDING,
            ))

        remaining_shares = total_shares - cliff_shares
        remaining_period = vesting_period - cliff_months

        if remaining_period <= 0 or remaining_shares <= 0:
            return schedules

        num_intervals = remaining_period // interval_months
        if num_intervals <= 0:
            num_intervals = 1

        shares_per_interval = remaining_shares // num_intervals
        remainder = remaining_shares - (shares_per_interval * num_intervals)

        for i in range(1, num_intervals + 1):
            vest_date = cliff_date + relativedelta(months=i * interval_months)
            shares = shares_per_interval
            if i == num_intervals:
                shares += remainder

            if shares > 0 and vest_date <= grant.expiration_date:
                schedules.append(VestingSchedule(
                    grant_id=grant.id,
                    vesting_date=vest_date,
                    scheduled_shares=shares,
                    status=VestingStatus.PENDING,
                ))

        return schedules


class GrantCalculator:
    GRANT_MULTIPLIERS = {
        EmployeeLevel.STAFF: {"base": Decimal("0.5"), "salary_multiplier": Decimal("0.3")},
        EmployeeLevel.MANAGER: {"base": Decimal("1.0"), "salary_multiplier": Decimal("0.6")},
        EmployeeLevel.DIRECTOR: {"base": Decimal("2.0"), "salary_multiplier": Decimal("1.0")},
        EmployeeLevel.VP: {"base": Decimal("4.0"), "salary_multiplier": Decimal("1.5")},
        EmployeeLevel.C_LEVEL: {"base": Decimal("8.0"), "salary_multiplier": Decimal("2.5")},
        EmployeeLevel.BOARD_MEMBER: {"base": Decimal("12.0"), "salary_multiplier": Decimal("3.0")},
    }

    @staticmethod
    def calculate_grant_amount(
        db: Session,
        employee: Employee,
        plan: EquityPlan,
        stock_price: Optional[Decimal] = None,
        custom_multiplier: Optional[Decimal] = None,
        custom_shares: Optional[int] = None,
    ) -> Dict[str, Any]:
        if custom_shares and custom_shares > 0:
            return {
                "total_shares": custom_shares,
                "calculation_method": "custom",
                "multiplier": custom_multiplier or Decimal("1"),
            }

        if stock_price is None:
            stock_price = StockPriceService.get_current_price(db)

        level_config = GrantCalculator.GRANT_MULTIPLIERS.get(
            employee.level,
            GrantCalculator.GRANT_MULTIPLIERS[EmployeeLevel.STAFF],
        )

        base_shares = int(level_config["base"] * 1000)
        salary = safe_decimal(employee.salary, Decimal("0"))
        salary_shares = 0
        if stock_price > 0:
            annual_salary = salary * 12
            salary_shares = int((annual_salary * level_config["salary_multiplier"]) / stock_price)

        multiplier = custom_multiplier or Decimal("1")
        total_shares = int((base_shares + salary_shares) * multiplier)

        available = safe_int(plan.shares_available, 0)
        if total_shares > available and available > 0:
            total_shares = available
            logger.warning(f"计划额度不足，授予数量调整为: {total_shares}")

        return {
            "total_shares": max(total_shares, 0),
            "calculation_method": "formula",
            "base_shares": base_shares,
            "salary_shares": salary_shares,
            "multiplier": multiplier,
            "stock_price": stock_price,
        }


class EquityPlanService:
    @staticmethod
    def create_plan(
        db: Session,
        plan_data: Dict[str, Any],
        operator_id: str = "system",
    ) -> EquityPlan:
        from utils.operation_log import OperationLogger
        from database.models import LogAction

        plan = EquityPlan(**{k: v for k, v in plan_data.items() if hasattr(EquityPlan, k)})
        plan.shares_available = plan.shares_available or plan.total_shares_reserved

        db.add(plan)
        db.flush()

        OperationLogger.log(
            db=db,
            action=LogAction.CREATE,
            resource_type="equity_plan",
            resource_id=str(plan.id),
            operator_id=operator_id,
            description=f"创建激励计划: {plan.plan_name} ({plan.plan_code})",
        )

        db.commit()
        db.refresh(plan)
        return plan

    @staticmethod
    def get_plan(db: Session, plan_id: int) -> Optional[EquityPlan]:
        return db.query(EquityPlan).filter(EquityPlan.id == plan_id).first()

    @staticmethod
    def get_plan_by_code(db: Session, plan_code: str) -> Optional[EquityPlan]:
        return db.query(EquityPlan).filter(EquityPlan.plan_code == plan_code).first()

    @staticmethod
    def list_active_plans(db: Session) -> List[EquityPlan]:
        return db.query(EquityPlan).filter(EquityPlan.is_active == True).all()


class GrantService:
    @staticmethod
    def create_grant(
        db: Session,
        employee: Employee,
        plan: EquityPlan,
        grant_date: date,
        custom_shares: Optional[int] = None,
        custom_price: Optional[Decimal] = None,
        custom_multiplier: Optional[Decimal] = None,
        performance_conditions: Optional[Dict[str, Any]] = None,
        operator_id: str = "system",
    ) -> EquityGrant:
        from utils.operation_log import OperationLogger
        from database.models import LogAction, TransactionType

        lock_key = f"grant_lock:plan_{plan.id}"
        if not redis_manager.acquire_lock(lock_key, timeout=30):
            raise RuntimeError("计划正在处理授予，请稍后重试")

        try:
            calc_result = GrantCalculator.calculate_grant_amount(
                db=db,
                employee=employee,
                plan=plan,
                custom_shares=custom_shares,
                custom_multiplier=custom_multiplier,
            )
            total_shares = calc_result["total_shares"]

            if total_shares <= 0:
                raise ValueError("授予数量必须大于0")

            if total_shares > safe_int(plan.shares_available):
                raise ValueError(f"计划可用额度不足，剩余: {plan.shares_available}")

            if custom_price:
                exercise_price = custom_price
            else:
                exercise_price = StockPriceService.calculate_grant_price(db, plan, grant_date)

            vesting_start = grant_date
            expiration = grant_date + relativedelta(months=plan.vesting_period_months + 12)

            grant = EquityGrant(
                grant_id=generate_id("GR"),
                employee_id=employee.employee_id,
                plan_id=plan.id,
                grant_date=grant_date,
                total_shares=total_shares,
                exercise_price=exercise_price,
                grant_price=exercise_price,
                currency="CNY",
                vesting_start_date=vesting_start,
                expiration_date=expiration,
                performance_conditions=performance_conditions or plan.performance_metrics,
                shares_outstanding=total_shares,
                status=VestingStatus.PENDING,
                extra_metadata={
                    "calculation": calc_result,
                },
            )

            db.add(grant)
            db.flush()

            schedules = VestingScheduleGenerator.generate_schedule(grant, plan)
            for schedule in schedules:
                schedule.grant_id = grant.id
                db.add(schedule)

            plan.shares_issued = safe_int(plan.shares_issued) + total_shares
            plan.shares_available = safe_int(plan.shares_available) - total_shares

            db.flush()

            OperationLogger.log(
                db=db,
                action=LogAction.CREATE,
                resource_type="equity_grant",
                resource_id=grant.grant_id,
                operator_id=operator_id,
                employee_id=employee.employee_id,
                transaction_type=TransactionType.GRANT,
                description=f"授予员工 {employee.name} {total_shares} 股 {plan.equity_type.value}",
                new_value={
                    "grant_id": grant.grant_id,
                    "total_shares": total_shares,
                    "exercise_price": float(exercise_price),
                    "plan_code": plan.plan_code,
                },
            )

            db.commit()
            db.refresh(grant)
            return grant

        finally:
            redis_manager.release_lock(lock_key)

    @staticmethod
    def process_vesting(db: Session, as_of_date: Optional[date] = None) -> Dict[str, int]:
        from utils.operation_log import OperationLogger
        from database.models import LogAction, TransactionType
        from services.shareholder import ShareholderService

        if as_of_date is None:
            as_of_date = date.today()

        pending_schedules = (
            db.query(VestingSchedule)
            .join(EquityGrant)
            .filter(
                VestingSchedule.vesting_date <= as_of_date,
                VestingSchedule.status == VestingStatus.PENDING,
                EquityGrant.status.in_([VestingStatus.PENDING, VestingStatus.VESTED]),
                EquityGrant.is_accepted == True,
            )
            .all()
        )

        vested_count = 0
        vested_shares = 0

        for schedule in pending_schedules:
            grant = schedule.grant
            if not grant:
                continue

            if plan := grant.plan:
                if plan.equity_type == EquityType.PERFORMANCE_STOCK:
                    if not grant.performance_achieved:
                        schedule.status = VestingStatus.FORFEITED
                        continue

            schedule.status = VestingStatus.VESTED
            schedule.vested_shares = schedule.scheduled_shares
            grant.shares_vested = safe_int(grant.shares_vested) + schedule.scheduled_shares
            grant.shares_outstanding = safe_int(grant.shares_outstanding) - schedule.scheduled_shares

            if grant.shares_vested > 0 and grant.status == VestingStatus.PENDING:
                grant.status = VestingStatus.VESTED

            vested_count += 1
            vested_shares += schedule.scheduled_shares

            OperationLogger.log(
                db=db,
                action=LogAction.UPDATE,
                resource_type="vesting_schedule",
                resource_id=str(schedule.id),
                operator_id="system",
                employee_id=grant.employee_id,
                transaction_type=TransactionType.VEST,
                description=f"归属 {schedule.scheduled_shares} 股，授予编号: {grant.grant_id}",
            )

            ShareholderService.update_record(db, grant.employee_id)

        db.commit()

        logger.info(f"归属处理完成: {vested_count} 条记录, {vested_shares} 股")
        return {"vested_count": vested_count, "vested_shares": vested_shares}

    @staticmethod
    def get_grant(db: Session, grant_id: str) -> Optional[EquityGrant]:
        return db.query(EquityGrant).filter(EquityGrant.grant_id == grant_id).first()

    @staticmethod
    def get_employee_grants(
        db: Session,
        employee_id: str,
        status: Optional[VestingStatus] = None,
    ) -> List[EquityGrant]:
        query = db.query(EquityGrant).filter(EquityGrant.employee_id == employee_id)
        if status:
            query = query.filter(EquityGrant.status == status)
        return query.order_by(EquityGrant.grant_date.desc()).all()

    @staticmethod
    def get_exercisable_shares(db: Session, grant: EquityGrant) -> int:
        total_vested = safe_int(grant.shares_vested)
        total_exercised = safe_int(grant.shares_exercised)
        return max(0, total_vested - total_exercised)
