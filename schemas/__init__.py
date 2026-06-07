from typing import Optional, List, Dict, Any
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict

from database.models import (
    EquityType, VestingStatus, ExerciseStatus, RepurchaseStatus,
    ApprovalLevel, ApprovalStatus, AgreementStatus, EmployeeLevel,
    TransactionType, LogAction,
)


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class EmployeeSchema(BaseSchema):
    employee_id: str
    name: str
    email: str
    phone: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    level: EmployeeLevel = EmployeeLevel.STAFF
    is_executive: bool = False
    hire_date: Optional[date] = None
    termination_date: Optional[date] = None
    is_active: bool = True
    salary: Optional[Decimal] = None
    currency: str = "CNY"
    country: Optional[str] = None
    created_at: Optional[datetime] = None


class EmployeeListResponse(BaseSchema):
    total: int
    items: List[EmployeeSchema]


class EquityPlanSchema(BaseSchema):
    id: Optional[int] = None
    plan_code: str
    plan_name: str
    equity_type: EquityType
    total_shares_reserved: int
    shares_issued: int = 0
    shares_available: int = 0
    effective_date: date
    expiration_date: date
    vesting_period_months: int = 48
    cliff_months: int = 12
    vesting_interval_months: int = 1
    cliff_percentage: Decimal = Decimal("0.25")
    exercise_price_method: str = "FMV_GRANT_DATE"
    is_active: bool = True


class EquityPlanCreate(BaseSchema):
    plan_code: str
    plan_name: str
    equity_type: EquityType
    total_shares_reserved: int
    effective_date: date
    expiration_date: date
    vesting_period_months: int = 48
    cliff_months: int = 12
    vesting_interval_months: int = 1
    cliff_percentage: Decimal = Decimal("0.25")
    exercise_price_method: str = "FMV_GRANT_DATE"
    exercise_price_discount: Optional[Decimal] = None
    min_exercise_price: Optional[Decimal] = None


class VestingScheduleSchema(BaseSchema):
    id: Optional[int] = None
    vesting_date: date
    scheduled_shares: int
    vested_shares: int = 0
    status: VestingStatus = VestingStatus.PENDING


class EquityGrantSchema(BaseSchema):
    id: Optional[int] = None
    grant_id: str
    employee_id: str
    plan_id: int
    grant_date: date
    total_shares: int
    exercise_price: Decimal
    vesting_start_date: date
    expiration_date: date
    shares_vested: int = 0
    shares_exercised: int = 0
    shares_forfeited: int = 0
    shares_outstanding: int = 0
    status: VestingStatus = VestingStatus.PENDING
    is_accepted: bool = False
    acceptance_date: Optional[date] = None
    vesting_schedules: List[VestingScheduleSchema] = []


class GrantCreateRequest(BaseSchema):
    employee_id: str
    plan_code: str
    grant_date: date
    custom_shares: Optional[int] = None
    custom_price: Optional[Decimal] = None
    custom_multiplier: Optional[Decimal] = None


class GrantCalculationResponse(BaseSchema):
    total_shares: int
    calculation_method: str
    exercise_price: Decimal
    vesting_schedule: List[Dict[str, Any]] = []


class ExerciseRequestCreate(BaseSchema):
    employee_id: str
    grant_id: str
    shares_to_exercise: int


class ExerciseRequestSchema(BaseSchema):
    id: Optional[int] = None
    request_id: str
    employee_id: str
    grant_id: int
    request_date: date
    shares_to_exercise: int
    current_stock_price: Decimal
    exercise_price: Decimal
    price_diff: Decimal
    gross_profit: Decimal
    tax_deferred_amount: Decimal
    taxable_amount: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    exercise_cost: Decimal
    net_payment_amount: Decimal
    deduction_amount: Decimal
    status: ExerciseStatus = ExerciseStatus.PENDING
    rejection_reason: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


class ExerciseValidationResponse(BaseSchema):
    is_valid: bool
    errors: List[str] = []
    warnings: List[str] = []
    exercisable_shares: int = 0
    current_price: Decimal
    exercise_price: Decimal
    price_diff: Decimal
    estimated_tax: Decimal
    estimated_total_cost: Decimal


class RepurchaseRequestCreate(BaseSchema):
    employee_id: str
    reason_type: str
    reason: str


class RepurchaseRequestSchema(BaseSchema):
    id: Optional[int] = None
    request_id: str
    employee_id: str
    total_shares: int
    repurchase_price_per_share: Decimal
    total_repurchase_amount: Decimal
    reason: Optional[str] = None
    repurchase_reason_type: Optional[str] = None
    status: RepurchaseStatus = RepurchaseStatus.DRAFT
    current_approval_level: Optional[ApprovalLevel] = None


class RepurchaseApprovalRequest(BaseSchema):
    approval_level: ApprovalLevel
    comments: Optional[str] = None
    vote_count: Optional[Dict[str, int]] = None


class AgreementSchema(BaseSchema):
    id: Optional[int] = None
    agreement_id: str
    agreement_type: str
    employee_id: str
    grant_id: Optional[int] = None
    status: AgreementStatus = AgreementStatus.GENERATED
    sent_at: Optional[datetime] = None
    signed_at: Optional[datetime] = None
    signed_by: Optional[str] = None
    archived_at: Optional[datetime] = None


class ExecutiveAlertSchema(BaseSchema):
    id: Optional[int] = None
    alert_id: str
    employee_id: str
    employee_name: str
    alert_type: str
    threshold_value: Decimal
    actual_value: Decimal
    percentage_reduced: Optional[Decimal] = None
    total_shares_before: int
    shares_reduced: int
    total_shares_after: int
    announcement_draft: Optional[str] = None
    is_approved: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


class MonthlyReportSchema(BaseSchema):
    id: Optional[int] = None
    report_id: str
    report_month: str
    total_grants_count: int = 0
    total_grants_shares: int = 0
    total_exercises_count: int = 0
    total_exercises_shares: int = 0
    total_repurchases_count: int = 0
    total_repurchases_shares: int = 0
    inventory_shares: int = 0
    outstanding_shares: int = 0
    vested_shares: int = 0
    average_profit_per_employee: Optional[Decimal] = None
    yoy_grants_growth: Optional[Decimal] = None
    yoy_exercises_growth: Optional[Decimal] = None
    yoy_repurchases_growth: Optional[Decimal] = None
    pdf_path: Optional[str] = None
    excel_path: Optional[str] = None
    is_generated: bool = False
    generated_at: Optional[datetime] = None


class OperationLogQuery(BaseSchema):
    employee_id: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    transaction_type: Optional[TransactionType] = None
    action: Optional[LogAction] = None
    resource_type: Optional[str] = None
    operator_id: Optional[str] = None
    skip: int = 0
    limit: int = 100


class OperationLogSchema(BaseSchema):
    id: Optional[int] = None
    log_id: str
    action: LogAction
    resource_type: str
    resource_id: Optional[str] = None
    operator_id: Optional[str] = None
    operator_name: Optional[str] = None
    transaction_type: Optional[TransactionType] = None
    employee_id: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[datetime] = None


class ShareholderRecordSchema(BaseSchema):
    id: Optional[int] = None
    employee_id: str
    share_type: str = "COMMON"
    total_shares_held: int = 0
    vested_shares: int = 0
    unvested_shares: int = 0
    exercisable_shares: int = 0
    exercised_shares: int = 0
    shares_available_for_sale: int = 0
    cost_basis: Decimal = Decimal("0")
    last_transaction_date: Optional[date] = None


class APIResponse(BaseSchema):
    success: bool = True
    message: str = "success"
    data: Optional[Any] = None
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PaginatedResponse(BaseSchema):
    success: bool = True
    message: str = "success"
    data: List[Any] = []
    total: int = 0
    skip: int = 0
    limit: int = 100


class HRSyncResponse(BaseSchema):
    status: str
    created: int = 0
    updated: int = 0
    inactivated: int = 0
    total: int = 0


class VestingProcessResponse(BaseSchema):
    vested_count: int
    vested_shares: int
