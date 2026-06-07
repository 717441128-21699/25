from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from pathlib import Path
import json
from sqlalchemy.orm import Session
from database.models import (
    Agreement, EquityGrant, Employee, AgreementStatus,
)
from utils.common import generate_id
from utils.logger import get_logger
from config import settings
from utils.operation_log import OperationLogger
from database.models import LogAction

logger = get_logger("agreement")


class AgreementTemplate:
    OPTION_TEMPLATE = """
    股票期权授予协议

    协议编号: {agreement_id}
    签署日期: {sign_date}

    甲方（公司）: {company_name}
    乙方（员工）: {employee_name}
    员工编号: {employee_id}
    身份证号: {id_number}

    鉴于乙方为甲方员工，根据公司股权激励计划，甲乙双方经友好协商，达成如下协议：

    第一条 授予内容
    1.1 甲方根据《{plan_name}》向乙方授予股票期权 {total_shares} 股。
    1.2 行权价格: 人民币 {exercise_price} 元/股。
    1.3 授予日期: {grant_date}。
    1.4 期权有效期至: {expiration_date}。

    第二条 归属安排
    2.1 本期权自授予之日起 {cliff_months} 个月为等待期。
    2.2 等待期满后，期权在 {vesting_period} 个月内按 {vesting_interval} 个月分期等额归属。
    2.3 首次归属比例为 {cliff_percentage}%。

    第三条 行权条件
    3.1 乙方在归属日仍为甲方正式员工。
    3.2 乙方满足绩效考核要求（如有）。
    3.3 不存在法律、法规或规章制度禁止行权的情形。

    第四条 离职处理
    4.1 乙方自愿离职的，已归属未行权期权自离职之日起30日内可行权，逾期作废。
    4.2 乙方因过错被解除劳动合同的，未归属期权作废，已归属期权甲方有权按原价回购。

    第五条 其他约定
    5.1 本协议项下期权不得转让、质押、担保。
    5.2 乙方行权所获股票的锁定期和减持限制适用法律法规及公司章程规定。
    5.3 本协议一式两份，甲乙双方各执一份，具有同等法律效力。

    甲方（盖章）: _______________
    乙方（签字）: _______________

    """

    RSU_TEMPLATE = """
    限制性股票授予协议

    协议编号: {agreement_id}
    签署日期: {sign_date}

    甲方（公司）: {company_name}
    乙方（员工）: {employee_name}
    员工编号: {employee_id}

    第一条 授予内容
    1.1 甲方向乙方授予限制性股票 {total_shares} 股。
    1.2 授予价格: 人民币 {exercise_price} 元/股。
    1.3 授予日期: {grant_date}。

    第二条 限售与解锁
    2.1 自授予之日起 {cliff_months} 个月为限售等待期。
    2.2 等待期满后分 {vesting_period} 期解锁。
    2.3 解锁条件: (1) 在职；(2) 绩效考核达标；(3) 公司业绩达标。

    第三条 回购条款
    3.1 乙方离职时，未解锁股票由公司按授予价格回购。
    3.2 乙方因严重违反规章制度被解除合同的，已解锁股票公司有权按原价回购。

    甲方（盖章）: _______________
    乙方（签字）: _______________
    """

    PERFORMANCE_TEMPLATE = """
    业绩股票授予协议

    协议编号: {agreement_id}
    签署日期: {sign_date}

    甲方（公司）: {company_name}
    乙方（员工）: {employee_name}
    员工编号: {employee_id}

    第一条 授予内容
    1.1 甲方根据业绩激励计划向乙方授予业绩股票 {total_shares} 股（目标数量）。
    1.2 实际授予数量根据绩效考核结果确定。

    第二条 业绩考核期
    2.1 考核期: {grant_date} 至 {expiration_date}。
    2.2 考核指标详见附件《绩效考核表》。

    第三条 归属规则
    3.1 考核结果为优秀的，按100%归属。
    3.2 考核结果为良好的，按80%归属。
    3.3 考核结果为合格的，按50%归属。
    3.4 考核结果为不合格的，不予归属。

    甲方（盖章）: _______________
    乙方（签字）: _______________
    """

    @classmethod
    def get_template(cls, equity_type: str) -> str:
        if equity_type == "OPTION":
            return cls.OPTION_TEMPLATE
        elif equity_type == "RESTRICTED_STOCK":
            return cls.RSU_TEMPLATE
        elif equity_type == "PERFORMANCE_STOCK":
            return cls.PERFORMANCE_TEMPLATE
        return cls.OPTION_TEMPLATE


class AgreementService:
    @staticmethod
    def _ensure_directories() -> None:
        Path(settings.agreement_template_dir).mkdir(parents=True, exist_ok=True)
        Path(settings.archive_dir).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def generate_grant_agreement(
        db: Session,
        grant: EquityGrant,
        company_name: str = "示例科技有限公司",
    ) -> Agreement:
        AgreementService._ensure_directories()

        employee = grant.employee
        plan = grant.plan

        template = AgreementTemplate.get_template(plan.equity_type.value if plan else "OPTION")

        context = {
            "agreement_id": generate_id("AGR"),
            "sign_date": datetime.now().strftime("%Y年%m月%d日"),
            "company_name": company_name,
            "employee_name": employee.name if employee else "",
            "employee_id": grant.employee_id,
            "id_number": employee.id_number if employee else "",
            "plan_name": plan.plan_name if plan else "",
            "total_shares": grant.total_shares,
            "exercise_price": f"{float(grant.exercise_price):.2f}",
            "grant_date": grant.grant_date.strftime("%Y年%m月%d日"),
            "expiration_date": grant.expiration_date.strftime("%Y年%m月%d日"),
            "cliff_months": plan.cliff_months if plan else 12,
            "vesting_period": plan.vesting_period_months if plan else 48,
            "vesting_interval": plan.vesting_interval_months if plan else 1,
            "cliff_percentage": f"{float(plan.cliff_percentage) * 100:.0f}" if plan else "25",
        }

        content = template.format(**context)

        agreement_id = context["agreement_id"]
        file_path = f"{settings.agreement_template_dir}/{agreement_id}.txt"
        Path(file_path).write_text(content, encoding="utf-8")

        agreement = Agreement(
            agreement_id=agreement_id,
            agreement_type="GRANT_AGREEMENT",
            employee_id=grant.employee_id,
            grant_id=grant.id,
            template_version="v1.0",
            generated_content=content,
            file_path=file_path,
            status=AgreementStatus.GENERATED,
            expires_at=datetime.utcnow() + timedelta(days=30),
        )

        db.add(agreement)
        db.flush()

        grant.agreement_id = agreement.id

        OperationLogger.log(
            db=db,
            action=LogAction.GENERATE,
            resource_type="agreement",
            resource_id=agreement_id,
            employee_id=grant.employee_id,
            description=f"生成授予协议: {agreement_id}",
        )

        db.commit()
        db.refresh(agreement)
        return agreement

    @staticmethod
    def send_agreement(
        db: Session,
        agreement_id: str,
        operator_id: str = "system",
    ) -> Agreement:
        agreement = (
            db.query(Agreement)
            .filter(Agreement.agreement_id == agreement_id)
            .first()
        )
        if not agreement:
            raise ValueError(f"协议不存在: {agreement_id}")

        if agreement.status != AgreementStatus.GENERATED:
            raise ValueError(f"协议状态不允许发送: {agreement.status.value}")

        agreement.status = AgreementStatus.SENT
        agreement.sent_at = datetime.utcnow()

        employee = db.query(Employee).filter(Employee.employee_id == agreement.employee_id).first()
        if employee:
            logger.info(f"已向 {employee.email} 发送协议签署通知: {agreement_id}")

        OperationLogger.log(
            db=db,
            action=LogAction.SEND,
            resource_type="agreement",
            resource_id=agreement_id,
            operator_id=operator_id,
            employee_id=agreement.employee_id,
            description=f"发送协议给员工签署",
        )

        db.commit()
        db.refresh(agreement)
        return agreement

    @staticmethod
    def sign_agreement(
        db: Session,
        agreement_id: str,
        signer_id: str,
        signer_name: str,
        signature_data: Optional[Dict[str, Any]] = None,
    ) -> Agreement:
        agreement = (
            db.query(Agreement)
            .filter(Agreement.agreement_id == agreement_id)
            .first()
        )
        if not agreement:
            raise ValueError(f"协议不存在: {agreement_id}")

        if agreement.status not in [AgreementStatus.GENERATED, AgreementStatus.SENT]:
            raise ValueError(f"协议状态不允许签署: {agreement.status.value}")

        agreement.status = AgreementStatus.SIGNED
        agreement.signed_at = datetime.utcnow()
        agreement.signed_by = signer_name
        agreement.signature_data = signature_data or {
            "sign_method": "electronic",
            "signed_by": signer_name,
            "signed_at": datetime.utcnow().isoformat(),
        }

        if agreement.grant_id:
            from database.models import EquityGrant
            grant = db.query(EquityGrant).filter(EquityGrant.id == agreement.grant_id).first()
            if grant:
                grant.is_accepted = True
                from datetime import date
                grant.acceptance_date = date.today()

        OperationLogger.log(
            db=db,
            action=LogAction.SIGN,
            resource_type="agreement",
            resource_id=agreement_id,
            operator_id=signer_id,
            operator_name=signer_name,
            employee_id=agreement.employee_id,
            description="员工签署协议完成",
        )

        db.commit()
        db.refresh(agreement)
        return agreement

    @staticmethod
    def archive_agreement(
        db: Session,
        agreement_id: str,
        operator_id: str = "system",
    ) -> Agreement:
        AgreementService._ensure_directories()

        agreement = (
            db.query(Agreement)
            .filter(Agreement.agreement_id == agreement_id)
            .first()
        )
        if not agreement:
            raise ValueError(f"协议不存在: {agreement_id}")

        if agreement.status != AgreementStatus.SIGNED:
            raise ValueError(f"协议状态不允许归档: {agreement.status.value}")

        archive_path = f"{settings.archive_dir}/{agreement_id}_signed.txt"
        if agreement.generated_content:
            Path(archive_path).write_text(agreement.generated_content, encoding="utf-8")

        agreement.status = AgreementStatus.ARCHIVED
        agreement.archived_at = datetime.utcnow()
        agreement.archive_path = archive_path

        OperationLogger.log(
            db=db,
            action=LogAction.ARCHIVE,
            resource_type="agreement",
            resource_id=agreement_id,
            operator_id=operator_id,
            employee_id=agreement.employee_id,
            description=f"协议归档完成，存储路径: {archive_path}",
        )

        db.commit()
        db.refresh(agreement)
        return agreement
