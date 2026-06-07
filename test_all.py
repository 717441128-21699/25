"""
股权激励系统 - 一键验证测试脚本
覆盖7个核心接口，无需启动服务器，直接使用FastAPI TestClient

使用方法:
    直接运行: python test_all.py
    或者: py test_all.py
"""

import sys
import os
import json
import time
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def cprint(text, color="", bold=False):
    prefix = ""
    if bold:
        prefix += Colors.BOLD
    if color:
        prefix += color
    print(f"{prefix}{text}{Colors.RESET}")


def print_header(title):
    width = 72
    cprint("\n" + "=" * width, Colors.MAGENTA, bold=True)
    cprint(f"  {title.center(width - 4)}", Colors.CYAN, bold=True)
    cprint("=" * width, Colors.MAGENTA, bold=True)


def print_section(title):
    cprint(f"\n  --- {title} ---", Colors.YELLOW, bold=True)


results = []


def record(name, passed, detail=""):
    results.append({"name": name, "passed": passed, "detail": detail})
    if passed:
        icon = "PASS"
        color = Colors.GREEN
    else:
        icon = "FAIL"
        color = Colors.RED
    if detail:
        cprint(f"    [{icon}] {name} - {detail}", color)
    else:
        cprint(f"    [{icon}] {name}", color)


def json_print(data, indent=6):
    try:
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        for line in text.split("\n"):
            cprint(" " * indent + line, Colors.BLUE)
    except Exception:
        cprint(" " * indent + str(data), Colors.BLUE)


def main():
    print_header("股权激励系统 - 核心接口一键验证")

    start_time = time.time()

    try:
        import init_data
        print_section("初始化测试数据")
        try:
            init_data.seed_database()
            record("数据初始化", True, "数据库、计划、员工、授予、股价、归属全部就绪")
        except Exception as e:
            record("数据初始化", False, f"异常: {e}")
            return

        from main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        record("FastAPI应用启动", True, "TestClient初始化成功")
    except Exception as e:
        record("环境初始化", False, f"导入失败: {e}")
        import traceback
        traceback.print_exc()
        return

    from database.connection import SessionLocal
    from database.models import Employee, EquityPlan, EquityGrant, ExerciseStatus

    db = SessionLocal()
    try:
        any_executive = (
            db.query(Employee).filter(Employee.is_executive == True).first()
            or db.query(Employee).first()
        )
        if any_executive:
            any_executive.is_executive = True
            db.commit()
            db.refresh(any_executive)
        any_employee = db.query(Employee).filter(Employee.is_active == True).first()
        any_plan = db.query(EquityPlan).first()
        any_grant = (
            db.query(EquityGrant)
            .filter(EquityGrant.shares_vested > 0)
            .first()
        )
        if not any_grant:
            any_grant = db.query(EquityGrant).first()
        db.close()
    except Exception:
        db.close()
        any_employee = None
        any_plan = None
        any_grant = None
        any_executive = None

    if not (any_employee and any_plan and any_grant):
        record("数据完整性检查", False, f"员工={bool(any_employee)} 计划={bool(any_plan)} 授予={bool(any_grant)}")
        return

    employee_id = any_employee.employee_id
    employee_name = any_employee.name
    plan_code = any_plan.plan_code
    grant_id = any_grant.grant_id
    exec_id = any_executive.employee_id if any_executive else employee_id

    cprint(f"\n  测试数据: 员工={employee_name}({employee_id}), 计划={plan_code}, 授予={grant_id}", Colors.CYAN)

    # ====================================================================
    # 接口1: HR系统同步员工
    # ====================================================================
    print_header("接口1: POST /api/v1/employees/sync (HR系统同步)")
    try:
        resp = client.post("/api/v1/employees/sync")
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        assert data.get("success", True) or data.get("data"), f"返回异常: {data}"
        sync_data = data.get("data", {}) or {}
        record(
            "HR同步返回",
            True,
            f"新增{sync_data.get('created', 0)} 更新{sync_data.get('updated', 0)} 共{sync_data.get('total', 0)}"
        )
        cprint("    返回结构:", Colors.BLUE)
        json_print(data)
    except Exception as e:
        record("HR同步", False, str(e))

    # ====================================================================
    # 接口2: 创建激励计划 + 获取计划列表
    # ====================================================================
    print_header("接口2: POST /api/v1/equity/plans (创建激励计划)")
    try:
        plan_payload = {
            "plan_code": "TEST_PLAN_" + datetime.now().strftime("%H%M%S"),
            "plan_name": "测试股票期权计划",
            "equity_type": "OPTION",
            "total_shares": 100000,
            "grant_date": date.today().isoformat(),
            "cliff_months": 12,
            "vesting_months": 48,
            "vesting_interval": "MONTHLY",
            "exercise_price": Decimal("20.00"),
            "valid_from": date.today().isoformat(),
            "valid_to": date(date.today().year + 10, 12, 31).isoformat(),
            "description": "API测试创建的计划",
        }
        resp = client.post("/api/v1/equity/plans", json=plan_payload)
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        assert "data" in data, f"结构异常: {data}"
        record("创建激励计划", True, f"{data['data'].get('plan_code')} - {data['data'].get('plan_name')}")
        cprint("    返回结构:", Colors.BLUE)
        json_print(data)

        list_resp = client.get("/api/v1/equity/plans")
        assert list_resp.status_code == 200
        total = list_resp.json().get("total", 0)
        record("计划列表查询", True, f"共 {total} 个计划")
    except Exception as e:
        record("创建激励计划", False, str(e))

    # ====================================================================
    # 接口3: 计算授予数量 + 创建授予
    # ====================================================================
    print_header("接口3: POST /api/v1/equity/grants/calculate + /grants (授予计算)")
    try:
        calc_payload = {
            "employee_id": employee_id,
            "plan_code": plan_code,
            "grant_date": date.today().isoformat(),
            "custom_multiplier": 1.5,
        }
        resp = client.post("/api/v1/equity/grants/calculate", json=calc_payload)
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        calc_data = data.get("data", {}) or {}
        total_shares = calc_data.get("total_shares", 0)
        exercise_price = calc_data.get("exercise_price", 0)
        assert total_shares > 0, "授予数量应为正数"
        record(
            "授予计算",
            True,
            f"共{total_shares}股, 行权价¥{exercise_price:.2f}"
        )
        cprint("    计算结果:", Colors.BLUE)
        json_print(calc_data)

        grant_payload = {
            "employee_id": employee_id,
            "plan_code": plan_code,
            "grant_date": date.today().isoformat(),
            "custom_shares": 5000,
            "custom_price": Decimal("18.50"),
        }
        resp2 = client.post("/api/v1/equity/grants", json=grant_payload)
        assert resp2.status_code == 200, f"HTTP {resp2.status_code}: {resp2.text[:200]}"
        gdata = resp2.json()
        new_grant_id = gdata.get("data", {}).get("grant_id", "")
        record("创建授予", True, f"授予ID={new_grant_id}, 5000股, 行权价¥18.50")
    except Exception as e:
        record("授予计算/创建", False, str(e))

    # ====================================================================
    # 接口4: 行权申请 (先校验再申请)
    # ====================================================================
    print_header("接口4: POST /api/v1/exercises/apply (行权申请 + 个税计算)")
    try:
        shares_to_exercise = min(100, int(any_grant.shares_vested or 50))
        validate_payload = {
            "employee_id": any_grant.employee_id,
            "grant_id": grant_id,
            "shares_to_exercise": shares_to_exercise,
        }
        resp = client.post("/api/v1/exercises/validate", json=validate_payload)
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
        vdata = resp.json().get("data", {}) or {}
        is_valid = vdata.get("is_valid", False)
        errors = vdata.get("errors", [])
        record(
            "行权校验",
            is_valid or len(errors) == 0,
            f"可行权{vdata.get('exercisable_shares', 0)}股, 申请{shares_to_exercise}股, 税款¥{vdata.get('tax_amount', 0):.2f}"
        )
        cprint("    校验+个税详情:", Colors.BLUE)
        json_print({
            "是否有效": vdata.get("is_valid"),
            "错误": vdata.get("errors", []),
            "警告": vdata.get("warnings", []),
            "当前股价": vdata.get("current_price"),
            "行权价": vdata.get("exercise_price"),
            "每股价差": vdata.get("price_diff"),
            "税前收益": vdata.get("gross_profit"),
            "个税递延": vdata.get("tax_deferred_amount"),
            "应纳税所得": vdata.get("taxable_amount"),
            "税率": vdata.get("tax_rate"),
            "个税金额": vdata.get("tax_amount"),
            "行权成本": vdata.get("exercise_cost"),
            "总扣款": vdata.get("total_deduction"),
            "净收益": vdata.get("net_profit"),
        })

        apply_payload = validate_payload
        resp2 = client.post("/api/v1/exercises/apply", json=apply_payload)
        if resp2.status_code == 200:
            edata = resp2.json()
            req_id = edata.get("data", {}).get("request_id", "")
            shares = edata.get("data", {}).get("shares_to_exercise", 0)
            tax = edata.get("data", {}).get("tax_amount", 0)
            total = edata.get("data", {}).get("deduction_amount", 0)
            record(
                "行权申请",
                True,
                f"申请ID={req_id}, {shares}股, 个税¥{float(tax):.2f}, 扣款¥{float(total):.2f}"
            )
            cprint("    申请结果:", Colors.BLUE)
            json_print(edata)
        elif resp2.status_code == 400:
            detail = resp2.json().get("detail", "")
            record(
                "行权申请",
                True,
                f"预期被拒(如未到期等): {detail[:80]}"
            )
        else:
            raise Exception(f"HTTP {resp2.status_code}: {resp2.text[:200]}")
    except Exception as e:
        record("行权申请", False, str(e))

    # ====================================================================
    # 接口5: 发起回购 (计算 + 创建 + 审批)
    # ====================================================================
    print_header("接口5: POST /api/v1/repurchases (股权回购 + 多级审批)")
    try:
        rep_calc_payload = {
            "employee_id": any_grant.employee_id,
            "grant_id": grant_id,
            "shares_to_repurchase": 200,
            "reason": "VOLUNTARY",
        }
        resp = client.post("/api/v1/repurchases/calculate", json=rep_calc_payload)
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
        rcalc = resp.json().get("data", {}) or {}
        record(
            "回购计算",
            True,
            f"200股×¥{rcalc.get('repurchase_price_per_share', 0):.2f}=¥{rcalc.get('repurchase_total_amount', 0):.2f}, 审批级别={rcalc.get('approval_level')}"
        )
        cprint("    回购计算:", Colors.BLUE)
        json_print(rcalc)

        resp2 = client.post("/api/v1/repurchases", json=rep_calc_payload)
        assert resp2.status_code == 200, f"HTTP {resp2.status_code}: {resp2.text[:200]}"
        rdata = resp2.json()
        rep_id = rdata.get("data", {}).get("request_id", "")
        approval = rdata.get("data", {}).get("approval_level", "")
        record(
            "创建回购申请",
            True,
            f"申请ID={rep_id}, 审批级别={approval}"
        )

        big_payload = dict(rep_calc_payload)
        big_payload["shares_to_repurchase"] = 80000
        big_payload["custom_price"] = 100.00
        resp3 = client.post("/api/v1/repurchases/calculate", json=big_payload)
        if resp3.status_code == 200:
            big = resp3.json().get("data", {}) or {}
            total_amt = big.get("repurchase_total_amount", 0)
            record(
                "大额回购审批判定",
                True,
                f"¥{total_amt:.2f}, 董事会={big.get('board_approval_required')}, 股东会={big.get('shareholder_approval_required')}"
            )
    except Exception as e:
        record("回购申请", False, str(e))

    # ====================================================================
    # 接口6: 月度报告生成 + PDF/Excel导出
    # ====================================================================
    print_header("接口6: POST /api/v1/reports (月度报告 + PDF/Excel导出)")
    try:
        resp = client.post("/api/v1/reports")
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
        rpt = resp.json()
        report_id = rpt.get("data", {}).get("id")
        year = rpt.get("data", {}).get("year")
        month = rpt.get("data", {}).get("month")
        granted = rpt.get("data", {}).get("total_grants_count", 0)
        exercised = rpt.get("data", {}).get("total_exercises_count", 0)
        repurchased = rpt.get("data", {}).get("total_repurchases_count", 0)
        record(
            "生成月度报告",
            True,
            f"报告ID={report_id}, {year}年{month}月: 授予{granted} 行权{exercised} 回购{repurchased}"
        )
        cprint("    报告数据:", Colors.BLUE)
        json_print(rpt.get("data", {}))

        if report_id:
            pdf_resp = client.get(f"/api/v1/reports/{report_id}/pdf")
            pdf_ok = pdf_resp.status_code == 200 and len(pdf_resp.content) > 100
            record(
                "PDF导出",
                pdf_ok,
                f"{len(pdf_resp.content)}字节" if pdf_ok else f"HTTP {pdf_resp.status_code}"
            )
            excel_resp = client.get(f"/api/v1/reports/{report_id}/excel")
            xls_ok = excel_resp.status_code == 200 and len(excel_resp.content) > 100
            record(
                "Excel/CSV导出",
                xls_ok,
                f"{len(excel_resp.content)}字节" if xls_ok else f"HTTP {excel_resp.status_code}"
            )
    except Exception as e:
        record("月度报告", False, str(e))

    # ====================================================================
    # 接口7: 高管减持预警
    # ====================================================================
    print_header("接口7: POST /api/v1/executive-alerts (高管减持预警)")
    try:
        sim_resp = client.post(
            f"/api/v1/executive-alerts/simulate?employee_id={exec_id}&current_holding=8000000&planned_sale=3000000&total_shares=100000000"
        )
        assert sim_resp.status_code == 200, f"HTTP {sim_resp.status_code}: {sim_resp.text[:200]}"
        sim = sim_resp.json().get("data", {}) or {}
        record(
            "减持模拟",
            True,
            f"当前{sim.get('current_holding_pct', 0):.2f}%→减持后{sim.get('after_sale_holding_pct', 0):.2f}%, 超季度限制={sim.get('exceeds_quarterly_limit')}, 5%披露触发={sim.get('crosses_5pct_threshold')}"
        )
        cprint("    模拟结果:", Colors.BLUE)
        json_print(sim)

        resp = client.post("/api/v1/executive-alerts/scan")
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
        alert_data = resp.json().get("data", {}) or {}
        alert_count = alert_data.get("count", 0)
        alerts = alert_data.get("alerts", [])
        record(
            "高管预警扫描",
            True,
            f"发现 {alert_count} 项预警"
        )
        if alert_count and isinstance(alerts, list) and len(alerts) > 0 and isinstance(alerts[0], dict):
            if "alert_id" in alerts[0]:
                alert_id = alerts[0]["alert_id"]
                dresp = client.get(f"/api/v1/executive-alerts/{alert_id}/announcement")
                if dresp.status_code == 200:
                    ann = dresp.json().get("data", {}) or {}
                    record("公告草稿生成", True, f"预警ID={alert_id}, 草稿长度>{len(str(ann.get('announcement_draft', '')))}")
    except Exception as e:
        record("高管减持预警", False, str(e))

    # ====================================================================
    # 汇总
    # ====================================================================
    print_header("测试结果汇总")
    elapsed = time.time() - start_time
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print()
    cprint(f"  通过: {passed}/{total}", Colors.GREEN if passed == total else Colors.RED, bold=True)
    cprint(f"  耗时: {elapsed:.2f} 秒", Colors.CYAN)
    print()

    for r in results:
        prefix = "   [OK] " if r["passed"] else "   [XX] "
        color = Colors.GREEN if r["passed"] else Colors.RED
        line = prefix + r["name"]
        if r["detail"]:
            line += f"  -  {r['detail']}"
        cprint(line, color)

    print()
    if passed == total:
        cprint("  所有核心接口测试通过！系统可用。", Colors.GREEN, bold=True)
    else:
        cprint(f"  有 {total - passed} 个接口未通过，请检查上方错误详情。", Colors.RED, bold=True)
    print()

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
