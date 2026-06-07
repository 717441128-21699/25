from typing import List, Dict, Any, Optional
from datetime import date, datetime
from sqlalchemy.orm import Session
from config import settings
from database.models import Employee, EmployeeLevel
from utils.common import parse_date, safe_decimal
from utils.logger import get_logger
from utils.operation_log import OperationLogger
from database.models import LogAction

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

try:
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
    HAS_TENACITY = True
except ImportError:
    HAS_TENACITY = False
    def retry(*args, **kwargs):
        def decorator(fn):
            return fn
        return decorator
    stop_after_attempt = lambda *a, **k: None
    wait_exponential = lambda *a, **k: None
    retry_if_exception_type = lambda *a, **k: None

logger = get_logger("hr_sync")


class MockHRSystemClient:
    """Mock HR系统客户端 - 用于演示和测试。生产环境请替换为真实API调用。"""

    def __init__(self):
        self.base_url = settings.hr_system_api_url
        self.api_key = settings.hr_system_api_key

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    )
    async def fetch_all_employees(self, last_sync_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params = {}
        if last_sync_time:
            params["updated_after"] = last_sync_time.isoformat()

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(
                    f"{self.base_url}/employees",
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.warning(f"连接HR系统失败，使用模拟数据: {e}")
            return self._generate_mock_employees()

    def _generate_mock_employees(self) -> List[Dict[str, Any]]:
        mock_employees = []
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

        for i in range(1, 501):
            level = levels[min(i // 100, len(levels) - 1)]
            positions = positions_by_level[level]
            department = departments[i % len(departments)]
            hire_year = 2015 + (i % 10)
            hire_month = (i % 12) + 1
            hire_day = (i % 28) + 1

            is_executive = level in [EmployeeLevel.C_LEVEL, EmployeeLevel.BOARD_MEMBER, EmployeeLevel.VP]

            mock_employees.append({
                "employee_id": f"EMP{i:06d}",
                "name": f"员工{i}",
                "email": f"employee{i}@company.com",
                "phone": f"138{i:08d}",
                "department": department,
                "position": positions[i % len(positions)],
                "level": level.value,
                "is_executive": is_executive,
                "hire_date": date(hire_year, hire_month, hire_day).isoformat(),
                "termination_date": None,
                "is_active": True,
                "salary": float((i + 1) * 5000),
                "currency": "CNY",
                "country": "中国",
                "id_number": f"110101{hire_year:04d}{hire_month:02d}{hire_day:02d}{i:04d}",
                "bank_account": f"622202{i:012d}",
                "bank_name": "中国工商银行",
                "tax_id": f"TAX{i:010d}",
            })

        return mock_employees

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    )
    async def fetch_employee_detail(self, employee_id: str) -> Optional[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/employees/{employee_id}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                if response.status_code == 200:
                    return response.json()
                return None
        except Exception as e:
            logger.warning(f"获取员工详情失败，返回None: {e}")
            return None


hr_client = MockHRSystemClient()


class EmployeeSyncService:
    @staticmethod
    def _map_hr_data_to_employee(hr_data: Dict[str, Any]) -> Employee:
        return Employee(
            employee_id=hr_data.get("employee_id"),
            name=hr_data.get("name"),
            email=hr_data.get("email"),
            phone=hr_data.get("phone"),
            department=hr_data.get("department"),
            position=hr_data.get("position"),
            level=EmployeeLevel(hr_data.get("level", "STAFF")),
            is_executive=hr_data.get("is_executive", False),
            hire_date=parse_date(hr_data.get("hire_date")),
            termination_date=parse_date(hr_data.get("termination_date")),
            is_active=hr_data.get("is_active", True),
            salary=safe_decimal(hr_data.get("salary")),
            currency=hr_data.get("currency", "CNY"),
            country=hr_data.get("country"),
            id_number=hr_data.get("id_number"),
            bank_account=hr_data.get("bank_account"),
            bank_name=hr_data.get("bank_name"),
            tax_id=hr_data.get("tax_id"),
            hr_data=hr_data,
        )

    @staticmethod
    def _update_employee_from_hr(employee: Employee, hr_data: Dict[str, Any]) -> None:
        employee.name = hr_data.get("name", employee.name)
        employee.email = hr_data.get("email", employee.email)
        employee.phone = hr_data.get("phone", employee.phone)
        employee.department = hr_data.get("department", employee.department)
        employee.position = hr_data.get("position", employee.position)
        employee.level = EmployeeLevel(hr_data.get("level", employee.level.value))
        employee.is_executive = hr_data.get("is_executive", employee.is_executive)
        employee.hire_date = parse_date(hr_data.get("hire_date")) or employee.hire_date
        employee.termination_date = parse_date(hr_data.get("termination_date"))
        employee.is_active = hr_data.get("is_active", employee.is_active)
        employee.salary = safe_decimal(hr_data.get("salary"), employee.salary)
        employee.currency = hr_data.get("currency", employee.currency)
        employee.country = hr_data.get("country", employee.country)
        employee.id_number = hr_data.get("id_number", employee.id_number)
        employee.bank_account = hr_data.get("bank_account", employee.bank_account)
        employee.bank_name = hr_data.get("bank_name", employee.bank_name)
        employee.tax_id = hr_data.get("tax_id", employee.tax_id)
        employee.hr_data = hr_data

    @classmethod
    async def sync_all_employees(cls, db: Session, operator_id: str = "system") -> Dict[str, int]:
        logger.info("开始同步HR系统员工数据...")

        lock_key = "hr_sync_lock"
        from utils.cache import redis_manager
        if not redis_manager.acquire_lock(lock_key, timeout=600):
            logger.warning("HR同步任务正在运行中，跳过本次执行")
            return {"status": "skipped", "reason": "lock_acquired"}

        try:
            hr_employees = await hr_client.fetch_all_employees()
            logger.info(f"从HR系统获取到 {len(hr_employees)} 名员工数据")

            created_count = 0
            updated_count = 0
            inactive_count = 0

            existing_ids = {
                emp.employee_id: emp
                for emp in db.query(Employee).all()
            }

            for hr_data in hr_employees:
                emp_id = hr_data.get("employee_id")
                if not emp_id:
                    continue

                if emp_id in existing_ids:
                    employee = existing_ids[emp_id]
                    cls._update_employee_from_hr(employee, hr_data)
                    updated_count += 1
                    OperationLogger.log(
                        db=db,
                        action=LogAction.UPDATE,
                        resource_type="employee",
                        resource_id=emp_id,
                        operator_id=operator_id,
                        operator_name="HR同步系统",
                        employee_id=emp_id,
                        description=f"从HR系统同步更新员工信息: {hr_data.get('name')}",
                    )
                else:
                    employee = cls._map_hr_data_to_employee(hr_data)
                    db.add(employee)
                    created_count += 1
                    OperationLogger.log(
                        db=db,
                        action=LogAction.CREATE,
                        resource_type="employee",
                        resource_id=emp_id,
                        operator_id=operator_id,
                        operator_name="HR同步系统",
                        employee_id=emp_id,
                        description=f"从HR系统新增员工: {hr_data.get('name')}",
                    )

            hr_ids = {e.get("employee_id") for e in hr_employees if e.get("employee_id")}
            for emp_id, employee in existing_ids.items():
                if emp_id not in hr_ids and employee.is_active:
                    employee.is_active = False
                    inactive_count += 1
                    OperationLogger.log(
                        db=db,
                        action=LogAction.UPDATE,
                        resource_type="employee",
                        resource_id=emp_id,
                        operator_id=operator_id,
                        operator_name="HR同步系统",
                        employee_id=emp_id,
                        description=f"员工在HR系统中不存在，标记为离职: {employee.name}",
                    )

            db.commit()

            result = {
                "created": created_count,
                "updated": updated_count,
                "inactivated": inactive_count,
                "total": len(hr_employees),
            }
            logger.info(f"HR同步完成: {result}")
            return result

        except Exception as e:
            db.rollback()
            logger.error(f"HR同步失败: {e}", exc_info=True)
            raise
        finally:
            redis_manager.release_lock(lock_key)

    @classmethod
    def get_employee(cls, db: Session, employee_id: str) -> Optional[Employee]:
        return db.query(Employee).filter(Employee.employee_id == employee_id).first()

    @classmethod
    def list_employees(
        cls,
        db: Session,
        department: Optional[str] = None,
        level: Optional[EmployeeLevel] = None,
        is_active: Optional[bool] = None,
        is_executive: Optional[bool] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Employee]:
        query = db.query(Employee)
        if department:
            query = query.filter(Employee.department == department)
        if level:
            query = query.filter(Employee.level == level)
        if is_active is not None:
            query = query.filter(Employee.is_active == is_active)
        if is_executive is not None:
            query = query.filter(Employee.is_executive == is_executive)
        return query.offset(skip).limit(limit).all()
