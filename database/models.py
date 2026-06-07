import enum
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import (
    Column, Integer, String, DateTime, Date, Numeric, Boolean,
    ForeignKey, Text, Enum, JSON, Float, BigInteger, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from database.connection import Base


class EquityType(str, enum.Enum):
    OPTION = "OPTION"
    RESTRICTED_STOCK = "RESTRICTED_STOCK"
    PERFORMANCE_STOCK = "PERFORMANCE_STOCK"


class VestingStatus(str, enum.Enum):
    PENDING = "PENDING"
    VESTED = "VESTED"
    EXERCISED = "EXERCISED"
    FORFEITED = "FORFEITED"
    EXPIRED = "EXPIRED"


class ExerciseStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RepurchaseStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    BOARD_APPROVED = "BOARD_APPROVED"
    SHAREHOLDER_APPROVED = "SHAREHOLDER_APPROVED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ApprovalLevel(str, enum.Enum):
    MANAGER = "MANAGER"
    BOARD = "BOARD"
    SHAREHOLDER = "SHAREHOLDER"


class ApprovalStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AgreementStatus(str, enum.Enum):
    GENERATED = "GENERATED"
    SENT = "SENT"
    SIGNED = "SIGNED"
    ARCHIVED = "ARCHIVED"
    REJECTED = "REJECTED"


class EmployeeLevel(str, enum.Enum):
    STAFF = "STAFF"
    MANAGER = "MANAGER"
    DIRECTOR = "DIRECTOR"
    VP = "VP"
    C_LEVEL = "C_LEVEL"
    BOARD_MEMBER = "BOARD_MEMBER"


class TransactionType(str, enum.Enum):
    GRANT = "GRANT"
    VEST = "VEST"
    EXERCISE = "EXERCISE"
    REPURCHASE = "REPURCHASE"
    FORFEITURE = "FORFEITURE"
    TRANSFER = "TRANSFER"
    ADJUSTMENT = "ADJUSTMENT"


class LogAction(str, enum.Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    SYNC = "SYNC"
    EXPORT = "EXPORT"
    GENERATE = "GENERATE"
    SEND = "SEND"
    SIGN = "SIGN"
    ARCHIVE = "ARCHIVE"
    ALERT = "ALERT"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"


class TimeStampedModel(Base):
    __abstract__ = True

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(100), nullable=True)
    updated_by = Column(String(100), nullable=True)


class Employee(TimeStampedModel):
    __tablename__ = "employees"

    employee_id = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    email = Column(String(200), nullable=False, index=True)
    phone = Column(String(50), nullable=True)
    department = Column(String(100), nullable=True, index=True)
    position = Column(String(100), nullable=True)
    level = Column(Enum(EmployeeLevel), default=EmployeeLevel.STAFF, nullable=False, index=True)
    is_executive = Column(Boolean, default=False, index=True)
    hire_date = Column(Date, nullable=True)
    termination_date = Column(Date, nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    salary = Column(Numeric(18, 2), nullable=True)
    currency = Column(String(10), default="CNY", nullable=True)
    country = Column(String(50), nullable=True)
    id_number = Column(String(50), nullable=True)
    bank_account = Column(String(100), nullable=True)
    bank_name = Column(String(200), nullable=True)
    tax_id = Column(String(50), nullable=True)
    hr_data = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)

    grants = relationship("EquityGrant", back_populates="employee", cascade="all, delete-orphan")
    shareholder_records = relationship("ShareholderRecord", back_populates="employee")
    exercises = relationship("ExerciseRequest", back_populates="employee")


class EquityPlan(TimeStampedModel):
    __tablename__ = "equity_plans"

    plan_code = Column(String(50), unique=True, nullable=False, index=True)
    plan_name = Column(String(200), nullable=False)
    equity_type = Column(Enum(EquityType), nullable=False, index=True)
    description = Column(Text, nullable=True)

    total_shares_reserved = Column(BigInteger, nullable=False)
    shares_issued = Column(BigInteger, default=0)
    shares_available = Column(BigInteger, default=0)

    effective_date = Column(Date, nullable=False)
    expiration_date = Column(Date, nullable=False)

    vesting_period_months = Column(Integer, default=48, nullable=False)
    cliff_months = Column(Integer, default=12, nullable=False)
    vesting_interval_months = Column(Integer, default=1, nullable=False)
    cliff_percentage = Column(Numeric(5, 4), default=Decimal("0.25"), nullable=False)

    exercise_price_method = Column(String(50), default="FMV_GRANT_DATE", nullable=False)
    exercise_price_discount = Column(Numeric(5, 4), default=Decimal("1.0"), nullable=True)
    min_exercise_price = Column(Numeric(18, 4), nullable=True)

    performance_metrics = Column(JSON, nullable=True)
    eligibility_criteria = Column(JSON, nullable=True)
    termination_forfeiture_rules = Column(JSON, nullable=True)

    transfer_restricted = Column(Boolean, default=True)
    repurchase_rights = Column(Boolean, default=True)
    repurchase_price_method = Column(String(50), default="ORIGINAL_PRICE", nullable=True)

    is_active = Column(Boolean, default=True, index=True)
    config = Column(JSON, nullable=True)

    grants = relationship("EquityGrant", back_populates="plan")


class EquityGrant(TimeStampedModel):
    __tablename__ = "equity_grants"

    grant_id = Column(String(50), unique=True, nullable=False, index=True)
    employee_id = Column(String(50), ForeignKey("employees.employee_id"), nullable=False, index=True)
    plan_id = Column(BigInteger, ForeignKey("equity_plans.id"), nullable=False, index=True)

    grant_date = Column(Date, nullable=False, index=True)
    total_shares = Column(BigInteger, nullable=False)
    exercise_price = Column(Numeric(18, 4), nullable=False)
    grant_price = Column(Numeric(18, 4), nullable=True)
    currency = Column(String(10), default="CNY", nullable=False)

    vesting_start_date = Column(Date, nullable=False)
    expiration_date = Column(Date, nullable=False)

    performance_conditions = Column(JSON, nullable=True)
    performance_achieved = Column(Boolean, default=True)

    shares_vested = Column(BigInteger, default=0)
    shares_exercised = Column(BigInteger, default=0)
    shares_forfeited = Column(BigInteger, default=0)
    shares_outstanding = Column(BigInteger, default=0)

    status = Column(Enum(VestingStatus), default=VestingStatus.PENDING, index=True)

    agreement_id = Column(BigInteger, ForeignKey("agreements.id"), nullable=True)
    acceptance_date = Column(Date, nullable=True)
    is_accepted = Column(Boolean, default=False)

    notes = Column(Text, nullable=True)
    metadata = Column(JSON, nullable=True)

    employee = relationship("Employee", back_populates="grants")
    plan = relationship("EquityPlan", back_populates="grants")
    vesting_schedules = relationship("VestingSchedule", back_populates="grant", cascade="all, delete-orphan")
    exercises = relationship("ExerciseRequest", back_populates="grant")


class VestingSchedule(TimeStampedModel):
    __tablename__ = "vesting_schedules"

    grant_id = Column(BigInteger, ForeignKey("equity_grants.id"), nullable=False, index=True)
    vesting_date = Column(Date, nullable=False, index=True)
    scheduled_shares = Column(BigInteger, nullable=False)
    vested_shares = Column(BigInteger, default=0)
    status = Column(Enum(VestingStatus), default=VestingStatus.PENDING, index=True)
    performance_metric = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)

    grant = relationship("EquityGrant", back_populates="vesting_schedules")

    __table_args__ = (
        Index("ix_grant_vesting_date", "grant_id", "vesting_date"),
    )


class ExerciseRequest(TimeStampedModel):
    __tablename__ = "exercise_requests"

    request_id = Column(String(50), unique=True, nullable=False, index=True)
    employee_id = Column(String(50), ForeignKey("employees.employee_id"), nullable=False, index=True)
    grant_id = Column(BigInteger, ForeignKey("equity_grants.id"), nullable=False, index=True)

    request_date = Column(Date, nullable=False, default=date.today, index=True)
    shares_to_exercise = Column(BigInteger, nullable=False)

    current_stock_price = Column(Numeric(18, 4), nullable=False)
    exercise_price = Column(Numeric(18, 4), nullable=False)
    price_diff = Column(Numeric(18, 4), nullable=False)

    gross_profit = Column(Numeric(18, 2), nullable=False)
    tax_deferred_amount = Column(Numeric(18, 2), default=Decimal("0"))
    taxable_amount = Column(Numeric(18, 2), nullable=False)
    tax_rate = Column(Numeric(5, 4), nullable=False)
    tax_amount = Column(Numeric(18, 2), nullable=False)

    exercise_cost = Column(Numeric(18, 2), nullable=False)
    net_payment_amount = Column(Numeric(18, 2), nullable=False)
    deduction_amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(10), default="CNY", nullable=False)

    deduction_order_id = Column(String(100), nullable=True)
    deduction_status = Column(String(50), nullable=True)
    settlement_date = Column(Date, nullable=True)

    status = Column(Enum(ExerciseStatus), default=ExerciseStatus.PENDING, index=True)
    rejection_reason = Column(Text, nullable=True)
    approved_by = Column(String(100), nullable=True)
    approved_at = Column(DateTime, nullable=True)

    tax_details = Column(JSON, nullable=True)
    metadata = Column(JSON, nullable=True)

    employee = relationship("Employee", back_populates="exercises")
    grant = relationship("EquityGrant", back_populates="exercises")


class RepurchaseRequest(TimeStampedModel):
    __tablename__ = "repurchase_requests"

    request_id = Column(String(50), unique=True, nullable=False, index=True)
    initiated_by = Column(String(100), nullable=False)

    employee_id = Column(String(50), ForeignKey("employees.employee_id"), nullable=False, index=True)
    grant_ids = Column(JSON, nullable=False)

    repurchase_date = Column(Date, nullable=True)
    total_shares = Column(BigInteger, nullable=False)
    repurchase_price_per_share = Column(Numeric(18, 4), nullable=False)
    total_repurchase_amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(10), default="CNY", nullable=False)

    reason = Column(Text, nullable=True)
    repurchase_reason_type = Column(String(50), nullable=True)

    status = Column(Enum(RepurchaseStatus), default=RepurchaseStatus.DRAFT, index=True)
    current_approval_level = Column(Enum(ApprovalLevel), nullable=True)

    approvals = relationship("ApprovalRecord", back_populates="repurchase_request")
    metadata = Column(JSON, nullable=True)


class ApprovalRecord(TimeStampedModel):
    __tablename__ = "approval_records"

    repurchase_id = Column(BigInteger, ForeignKey("repurchase_requests.id"), nullable=False, index=True)
    approval_level = Column(Enum(ApprovalLevel), nullable=False)
    approver = Column(String(100), nullable=False)
    status = Column(Enum(ApprovalStatus), default=ApprovalStatus.PENDING, index=True)
    decision_date = Column(DateTime, nullable=True)
    comments = Column(Text, nullable=True)
    vote_count = Column(JSON, nullable=True)

    repurchase_request = relationship("RepurchaseRequest", back_populates="approvals")


class ShareholderRecord(TimeStampedModel):
    __tablename__ = "shareholder_records"

    employee_id = Column(String(50), ForeignKey("employees.employee_id"), nullable=False, index=True)
    share_type = Column(String(50), nullable=False)

    total_shares_held = Column(BigInteger, default=0)
    vested_shares = Column(BigInteger, default=0)
    unvested_shares = Column(BigInteger, default=0)
    exercisable_shares = Column(BigInteger, default=0)
    exercised_shares = Column(BigInteger, default=0)
    shares_available_for_sale = Column(BigInteger, default=0)

    last_transaction_date = Column(Date, nullable=True)
    cost_basis = Column(Numeric(18, 2), default=Decimal("0"))
    currency = Column(String(10), default="CNY", nullable=False)

    employee = relationship("Employee", back_populates="shareholder_records")

    __table_args__ = (
        UniqueConstraint("employee_id", "share_type", name="uq_employee_share_type"),
    )


class Agreement(TimeStampedModel):
    __tablename__ = "agreements"

    agreement_id = Column(String(50), unique=True, nullable=False, index=True)
    agreement_type = Column(String(50), nullable=False)

    employee_id = Column(String(50), ForeignKey("employees.employee_id"), nullable=False, index=True)
    grant_id = Column(BigInteger, ForeignKey("equity_grants.id"), nullable=True, index=True)

    template_version = Column(String(50), nullable=True)
    generated_content = Column(Text, nullable=True)
    file_path = Column(String(500), nullable=True)

    status = Column(Enum(AgreementStatus), default=AgreementStatus.GENERATED, index=True)
    sent_at = Column(DateTime, nullable=True)
    signed_at = Column(DateTime, nullable=True)
    signed_by = Column(String(100), nullable=True)
    signature_data = Column(JSON, nullable=True)
    archived_at = Column(DateTime, nullable=True)
    archive_path = Column(String(500), nullable=True)

    expires_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)


class StockPrice(TimeStampedModel):
    __tablename__ = "stock_prices"

    trade_date = Column(Date, nullable=False, index=True)
    price = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(10), default="CNY", nullable=False)
    open_price = Column(Numeric(18, 4), nullable=True)
    high_price = Column(Numeric(18, 4), nullable=True)
    low_price = Column(Numeric(18, 4), nullable=True)
    close_price = Column(Numeric(18, 4), nullable=True)
    volume = Column(BigInteger, nullable=True)
    source = Column(String(50), nullable=True)

    __table_args__ = (
        UniqueConstraint("trade_date", "currency", name="uq_trade_date_currency"),
    )


class ExecutiveAlert(TimeStampedModel):
    __tablename__ = "executive_alerts"

    alert_id = Column(String(50), unique=True, nullable=False, index=True)
    employee_id = Column(String(50), ForeignKey("employees.employee_id"), nullable=False, index=True)
    employee_name = Column(String(200), nullable=False)

    alert_type = Column(String(50), nullable=False)
    threshold_value = Column(Numeric(18, 4), nullable=False)
    actual_value = Column(Numeric(18, 4), nullable=False)
    percentage_reduced = Column(Numeric(10, 4), nullable=True)

    total_shares_before = Column(BigInteger, nullable=False)
    shares_reduced = Column(BigInteger, nullable=False)
    total_shares_after = Column(BigInteger, nullable=False)

    announcement_draft = Column(Text, nullable=True)
    is_approved = Column(Boolean, default=False)
    approved_by = Column(String(100), nullable=True)
    approved_at = Column(DateTime, nullable=True)

    notes = Column(Text, nullable=True)
    metadata = Column(JSON, nullable=True)


class MonthlyReport(TimeStampedModel):
    __tablename__ = "monthly_reports"

    report_id = Column(String(50), unique=True, nullable=False, index=True)
    report_month = Column(String(7), nullable=False, index=True)

    total_grants_count = Column(Integer, default=0)
    total_grants_shares = Column(BigInteger, default=0)
    total_exercises_count = Column(Integer, default=0)
    total_exercises_shares = Column(BigInteger, default=0)
    total_repurchases_count = Column(Integer, default=0)
    total_repurchases_shares = Column(BigInteger, default=0)

    inventory_shares = Column(BigInteger, default=0)
    outstanding_shares = Column(BigInteger, default=0)
    vested_shares = Column(BigInteger, default=0)
    average_profit_per_employee = Column(Numeric(18, 2), nullable=True)

    yoy_grants_growth = Column(Numeric(10, 4), nullable=True)
    yoy_exercises_growth = Column(Numeric(10, 4), nullable=True)
    yoy_repurchases_growth = Column(Numeric(10, 4), nullable=True)

    summary_data = Column(JSON, nullable=True)
    chart_data = Column(JSON, nullable=True)

    pdf_path = Column(String(500), nullable=True)
    excel_path = Column(String(500), nullable=True)

    is_generated = Column(Boolean, default=False)
    generated_at = Column(DateTime, nullable=True)


class OperationLog(TimeStampedModel):
    __tablename__ = "operation_logs"

    log_id = Column(String(50), unique=True, nullable=False, index=True)
    action = Column(Enum(LogAction), nullable=False, index=True)
    resource_type = Column(String(100), nullable=False, index=True)
    resource_id = Column(String(100), nullable=True, index=True)

    operator_id = Column(String(50), nullable=True, index=True)
    operator_name = Column(String(200), nullable=True)
    operator_role = Column(String(100), nullable=True)

    transaction_type = Column(Enum(TransactionType), nullable=True, index=True)
    employee_id = Column(String(50), nullable=True, index=True)

    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)

    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)
    changed_fields = Column(JSON, nullable=True)

    description = Column(Text, nullable=True)
    metadata = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_logs_employee_time", "employee_id", "created_at"),
        Index("ix_logs_action_time", "action", "created_at"),
        Index("ix_logs_transaction_time", "transaction_type", "created_at"),
    )
