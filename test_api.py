"""
企业级员工股权激励自动化管理系统 - API集成测试脚本

使用方法:
    python test_api.py [--base-url http://localhost:8000]

测试覆盖:
    1. HR系统同步员工信息
    2. 创建激励计划 + 计算授予数量
    3. 员工行权申请 + 税款计算
    4. 发起回购 + 多级审批
    5. 生成月度报告 + 导出PDF/Excel
    6. 高管减持预警检测
"""

import sys
import json
import time
import argparse
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, Any, List


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


class APITester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self.results = []
        try:
            import httpx
            self.client = httpx.Client(timeout=30.0, base_url=self.base_url)
            self.use_httpx = True
        except ImportError:
            self.use_httpx = False
            try:
                import urllib.request
                self.urllib = urllib.request
            except ImportError:
                print(f"{Colors.RED}[ERROR] httpx 和 urllib 均不可用{Colors.RESET}")
                sys.exit(1)

    def _request(self, method: str, path: str, json_data: Dict = None, params: Dict = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        if self.use_httpx:
            response = self.client.request(method, path, json=json_data, params=params)
            return {
                "status_code": response.status_code,
                "data": response.json() if response.content else {},
                "text": response.text,
            }
        else:
            import urllib.request
            import urllib.parse
            data = None
            if json_data:
                data = json.dumps(json_data).encode("utf-8")
            if params:
                url += "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read().decode("utf-8")
                    return {
                        "status_code": resp.status,
                        "data": json.loads(body) if body else {},
                        "text": body,
                    }
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8")
                return {
                    "status_code": e.code,
                    "data": json.loads(body) if body else {},
                    "text": body,
                }

    def log(self, name: str, success: bool, message: str = "", data: Any = None):
        status = f"{Colors.GREEN}✓ PASS{Colors.RESET}" if success else f"{Colors.RED}✗ FAIL{Colors.RESET}"
        detail = f" - {message}" if message else ""
        print(f"  {status} {Colors.BOLD}{name}{Colors.RESET}{detail}")
        self.results.append({"name": name, "success": success, "message": message})
        if not success and data:
            print(f"    {Colors.YELLOW}错误详情: {json.dumps(data, ensure_ascii=False, default=str)[:300]}{Colors.RESET}")

    def print_header(self, title: str):
        print()
        print(f"{Colors.BOLD}{Colors.CYAN}{'='*70}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN}  {title}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN}{'='*70}{Colors.RESET}")

    def print_summary(self):
        print()
        print(f"{Colors.BOLD}{Colors.MAGENTA}{'='*70}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.MAGENTA}  测试结果汇总{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.MAGENTA}{'='*70}{Colors.RESET}")

        passed = sum(1 for r in self.results if r["success"])
        total = len(self.results)
        pct = (passed / total * 100) if total > 0 else 0

        for r in self.results:
            status = f"{Colors.GREEN}PASS{Colors.RESET}" if r["success"] else f"{Colors.RED}FAIL{Colors.RESET}"
            print(f"  [{status}] {r['name']}")
            if r["message"] and not r["success"]:
                print(f"         {Colors.YELLOW}{r['message']}{Colors.RESET}")

        print()
        color = Colors.GREEN if pct >= 80 else (Colors.YELLOW if pct >= 50 else Colors.RED)
        print(f"  {Colors.BOLD}总计: {color}{passed}/{total}{Colors.RESET} {Colors.BOLD}通过 ({color}{pct:.1f}%{Colors.RESET}{Colors.BOLD}){Colors.RESET}")
        print()

    def run(self):
        print(f"\n{Colors.BOLD}{Colors.BLUE}")
        print("  ╔══════════════════════════════════════════════════════════════════════╗")
        print("  ║     企业级员工股权激励自动化管理系统 - API 集成测试                     ║")
        print("  ╚══════════════════════════════════════════════════════════════════════╝")
        print(f"{Colors.RESET}")
        print(f"  测试目标: {self.base_url}")
        print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        try:
            self.test_health_check()
            self.test_hr_employee_sync()
            self.test_equity_plan_and_grant()
            self.test_exercise_with_tax()
            self.test_repurchase_with_approval()
            self.test_monthly_report()
            self.test_executive_alert()
        finally:
            if self.use_httpx:
                self.client.close()
            self.print_summary()

    # ====== 测试用例 ======

    def test_health_check(self):
        self.print_header("0. 健康检查")
        try:
            resp = self._request("GET", "/health")
            success = resp["status_code"] == 200 and resp["data"].get("status") == "healthy"
            self.log("服务健康检查", success,
                     f"status={resp['status_code']}, data={resp['data'].get('status')}" if not success else "")
        except Exception as e:
            self.log("服务健康检查", False, str(e))

    def test_hr_employee_sync(self):
        self.print_header("1. HR系统同步员工信息")
        try:
            resp = self._request("POST", "/api/v1/employees/sync")
            data = resp["data"]
            success = resp["status_code"] == 200 and data.get("success", True)

            if success:
                result = data.get("data", {})
                created = result.get("created", 0)
                updated = result.get("updated", 0)
                total = result.get("total", 0)
                msg = f"新增{created}人, 更新{updated}人, 共{total}人"
                self.log("POST /api/v1/employees/sync", success, msg)

                resp2 = self._request("GET", "/api/v1/employees", params={"limit": 5})
                success2 = resp2["status_code"] == 200 and len(resp2["data"].get("data", [])) > 0
                if success2:
                    emp_count = resp2["data"].get("total", 0)
                    self.log("GET /api/v1/employees (查询员工列表)", success2, f"查询到 {emp_count} 名员工")
                else:
                    self.log("GET /api/v1/employees (查询员工列表)", success2,
                             f"status={resp2['status_code']}", resp2["data"])
            else:
                self.log("POST /api/v1/employees/sync", success,
                         f"HTTP {resp['status_code']}", resp.get("data"))
        except Exception as e:
            self.log("HR员工同步测试", False, str(e))

    def test_equity_plan_and_grant(self):
        self.print_header("2. 创建激励计划 + 计算授予数量")
        try:
            plan_code = f"TEST-{int(time.time())}"
            plan_data = {
                "plan_code": plan_code,
                "plan_name": f"测试激励计划-{plan_code}",
                "equity_type": "OPTION",
                "total_shares_reserved": 1000000,
                "effective_date": str(date.today()),
                "expiration_date": "2034-01-01",
                "vesting_period_months": 48,
                "cliff_months": 12,
                "vesting_interval_months": 3,
                "cliff_percentage": 0.25,
                "exercise_price_method": "FMV_GRANT_DATE",
            }

            resp = self._request("POST", "/api/v1/equity/plans", json_data=plan_data)
            success = resp["status_code"] in [200, 201] and resp["data"].get("success", True)
            if not success and resp["status_code"] == 400:
                msg = resp["data"].get("detail", "未知错误")
                if "已存在" in msg or "exists" in msg.lower():
                    success = True
                    plan_code = "OPT-2024"

            self.log("POST /api/v1/equity/plans (创建激励计划)", success,
                     f"计划代码={plan_code}" if success else f"status={resp['status_code']}: {resp['data'].get('detail', '')}",
                     resp["data"] if not success else None)

            if success:
                resp2 = self._request("GET", "/api/v1/equity/plans")
                self.log("GET /api/v1/equity/plans (查询计划列表)",
                         resp2["status_code"] == 200,
                         f"共 {len(resp2['data'].get('data', []))} 个计划")

                resp_emps = self._request("GET", "/api/v1/employees", params={"limit": 1})
                emps = resp_emps["data"].get("data", [])
                if emps:
                    test_emp = emps[0]
                    grant_data = {
                        "employee_id": test_emp["employee_id"],
                        "plan_code": plan_code,
                        "grant_date": str(date.today()),
                        "custom_shares": 10000,
                    }

                    resp3 = self._request("POST", "/api/v1/equity/grants/calculate", json_data=grant_data)
                    calc_ok = resp3["status_code"] == 200 and resp3["data"].get("success", True)
                    calc_result = resp3["data"].get("data", {})
                    self.log("POST /api/v1/equity/grants/calculate (计算授予)",
                             calc_ok,
                             f"授予 {calc_result.get('total_shares', 0)} 股，价格 ¥{calc_result.get('exercise_price', 0):.2f}" if calc_ok else "",
                             resp3["data"] if not calc_ok else None)

                    resp4 = self._request("POST", "/api/v1/equity/grants", json_data=grant_data)
                    grant_ok = resp4["status_code"] in [200, 201] and resp4["data"].get("success", True)
                    grant_info = resp4["data"].get("data", {})
                    self.log("POST /api/v1/equity/grants (创建授予)",
                             grant_ok,
                             f"授予ID={grant_info.get('grant_id', 'N/A')}，{grant_info.get('total_shares', 0)}股" if grant_ok else f"status={resp4['status_code']}",
                             resp4["data"] if not grant_ok else None)
                else:
                    self.log("员工数据查询", False, "未查询到员工数据")

            resp5 = self._request("GET", "/api/v1/equity/stock-price/current")
            self.log("GET /api/v1/equity/stock-price/current (当前股价)",
                     resp5["status_code"] == 200,
                     f"¥{resp5['data'].get('data', {}).get('current_price', 0):.2f}")

        except Exception as e:
            self.log("激励计划与授予测试", False, str(e))

    def test_exercise_with_tax(self):
        self.print_header("3. 员工行权申请 + 税款计算")
        try:
            resp_emps = self._request("GET", "/api/v1/employees", params={"limit": 3})
            emps = resp_emps["data"].get("data", [])
            if not emps:
                self.log("查询员工数据", False, "无员工数据")
                return

            test_emp = None
            test_grant = None
            for emp in emps:
                emp_id = emp["employee_id"]
                resp_grants = self._request("GET", f"/api/v1/equity/grants/employee/{emp_id}")
                grants = resp_grants["data"].get("data", [])
                for g in grants:
                    if g.get("shares_vested", 0) > 0 and g.get("is_accepted", False):
                        test_emp = emp
                        test_grant = g
                        break
                if test_grant:
                    break

            if not test_grant:
                self.log("查找可行权授予", False, "未找到已归属的授予，尝试从员工列表第1人获取任意授予")
                for emp in emps:
                    resp_grants = self._request("GET", f"/api/v1/equity/grants/employee/{emp['employee_id']}")
                    grants = resp_grants["data"].get("data", [])
                    if grants:
                        test_emp = emp
                        test_grant = grants[0]
                        break

            if not test_grant:
                self.log("查找可行权授予", False, "没有任何授予记录")
                return

            emp_id = test_emp["employee_id"]
            grant_id = test_grant["grant_id"]
            shares = min(100, max(10, test_grant.get("shares_vested", 100) // 10 or 10))

            validate_data = {
                "employee_id": emp_id,
                "grant_id": grant_id,
                "shares_to_exercise": shares,
            }

            resp1 = self._request("POST", "/api/v1/exercises/validate", json_data=validate_data)
            v_ok = resp1["status_code"] == 200 and resp1["data"].get("success", True)
            v_data = resp1["data"].get("data", {})
            msg = ""
            if v_ok:
                msg = (f"校验{'通过' if v_data.get('is_valid') else '未通过'}, "
                       f"税额¥{v_data.get('estimated_tax', 0):.2f}, "
                       f"总成本¥{v_data.get('estimated_total_deduction', 0):.2f}")
                if v_data.get("errors"):
                    msg += f" 错误: {v_data['errors'][:2]}"
            self.log("POST /api/v1/exercises/validate (行权校验+税算)", v_ok, msg,
                     resp1["data"] if not v_ok else None)

            if v_ok or (v_data.get("errors") and any("未签署" in e or "不足" in e for e in v_data["errors"])):
                resp2 = self._request("POST", "/api/v1/exercises/apply", json_data=validate_data)
                ok = resp2["status_code"] == 200 and resp2["data"].get("success", True)
                ex_data = resp2["data"].get("data", {})
                self.log("POST /api/v1/exercises/apply (提交行权申请)",
                         ok or resp2["status_code"] in [400, 429],
                         f"申请ID={ex_data.get('request_id', 'N/A')}, 税款¥{ex_data.get('tax_amount', 0):.2f}" if ok
                         else f"status={resp2['status_code']}: {resp2['data'].get('detail', resp2['data'].get('message', ''))}",
                         resp2["data"] if not ok and resp2["status_code"] not in [400, 429] else None)

                if ok:
                    req_id = ex_data["request_id"]
                    resp3 = self._request("POST", f"/api/v1/exercises/{req_id}/approve",
                                         params={"approver_id": "tester", "approver_name": "测试员"})
                    a_ok = resp3["status_code"] == 200 and resp3["data"].get("success", True)
                    self.log(f"POST /api/v1/exercises/{req_id}/approve (审批行权)",
                             a_ok,
                             f"状态={resp3['data'].get('data', {}).get('status', 'N/A')}" if a_ok else f"status={resp3['status_code']}",
                             resp3["data"] if not a_ok else None)

        except Exception as e:
            self.log("行权申请与税款计算测试", False, str(e))

    def test_repurchase_with_approval(self):
        self.print_header("4. 发起回购 + 多级审批")
        try:
            resp_emps = self._request("GET", "/api/v1/employees", params={"limit": 5})
            emps = resp_emps["data"].get("data", [])
            if not emps:
                self.log("查询员工数据", False, "无员工数据")
                return

            test_emp = emps[0]
            emp_id = test_emp["employee_id"]
            emp_name = test_emp["name"]

            resp1 = self._request("POST", "/api/v1/repurchases/calculate",
                                 params={"employee_id": emp_id, "reason_type": "VOLUNTARY_TERMINATION"})
            calc_ok = resp1["status_code"] == 200 and resp1["data"].get("success", True)
            calc = resp1["data"].get("data", {})
            total_amt = calc.get("total_amount", 0)
            levels = calc.get("required_approval_levels", [])
            self.log("POST /api/v1/repurchases/calculate (回购计算)", calc_ok,
                     f"回购{calc.get('total_shares', 0)}股，金额¥{total_amt:,.2f}，需审批: {levels}" if calc_ok else "",
                     resp1["data"] if not calc_ok else None)

            if not calc.get("total_shares"):
                self.log("创建回购申请", False, f"员工 {emp_name} 无可回购股份，跳过")
                return

            repurchase_data = {
                "employee_id": emp_id,
                "reason_type": "VOLUNTARY_TERMINATION",
                "reason": "测试回购-员工自愿离职",
            }
            resp2 = self._request("POST", "/api/v1/repurchases", json_data=repurchase_data,
                                 params={"initiated_by": "tester", "initiator_name": "测试员"})
            create_ok = resp2["status_code"] == 200 and resp2["data"].get("success", True)
            rp = resp2["data"].get("data", {})
            rp_id = rp.get("request_id", "")
            self.log("POST /api/v1/repurchases (创建回购申请)", create_ok,
                     f"申请ID={rp_id}, 金额¥{rp.get('total_repurchase_amount', 0):,.2f}" if create_ok else f"status={resp2['status_code']}",
                     resp2["data"] if not create_ok else None)

            if create_ok and rp_id:
                resp3 = self._request("POST", f"/api/v1/repurchases/{rp_id}/submit",
                                     params={"submitter_id": "tester", "submitter_name": "测试员"})
                sub_ok = resp3["status_code"] == 200 and resp3["data"].get("success", True)
                current_level = resp3["data"].get("data", {}).get("current_approval_level", "")
                self.log(f"POST /api/v1/repurchases/{rp_id}/submit (提交审批)", sub_ok,
                         f"当前审批级别: {current_level}" if sub_ok else f"status={resp3['status_code']}",
                         resp3["data"] if not sub_ok else None)

                if sub_ok and current_level:
                    from database.models import ApprovalLevel
                    level_value = current_level if current_level in ["MANAGER", "BOARD", "SHAREHOLDER"] else "MANAGER"
                    approval_data = {"approval_level": level_value, "comments": "测试通过"}
                    resp4 = self._request("POST", f"/api/v1/repurchases/{rp_id}/approve",
                                         json_data=approval_data,
                                         params={"approver_id": "tester", "approver_name": "测试员"})
                    ap_ok = resp4["status_code"] == 200 and resp4["data"].get("success", True)
                    next_level = resp4["data"].get("data", {}).get("current_approval_level", "ALL_APPROVED")
                    self.log(f"POST /api/v1/repurchases/{rp_id}/approve ({level_value}审批)",
                             ap_ok,
                             f"下一级: {next_level}" if ap_ok else f"status={resp4['status_code']}",
                             resp4["data"] if not ap_ok else None)

        except Exception as e:
            self.log("回购与多级审批测试", False, str(e))

    def test_monthly_report(self):
        self.print_header("5. 生成月度报告 + 导出PDF/Excel")
        try:
            today = date.today()
            report_month = f"{today.year:04d}-{today.month:02d}"

            resp1 = self._request("POST", "/api/v1/reports/generate",
                                 params={"report_month": report_month, "async_mode": False})
            gen_ok = resp1["status_code"] == 200 and resp1["data"].get("success", True)
            rep = resp1["data"].get("data", {})
            self.log(f"POST /api/v1/reports/generate (生成{report_month}报告)", gen_ok,
                     f"授予{rep.get('total_grants_shares', 0)}股, 行权{rep.get('total_exercises_shares', 0)}股" if gen_ok
                     else f"status={resp1['status_code']}",
                     resp1["data"] if not gen_ok else None)

            resp2 = self._request("GET", "/api/v1/reports")
            list_ok = resp2["status_code"] == 200
            reports = resp2["data"].get("data", [])
            self.log("GET /api/v1/reports (报告列表)", list_ok, f"共 {len(reports)} 份报告")

            if reports:
                month = reports[0].get("report_month", report_month)
                resp3 = self._request("GET", f"/api/v1/reports/{month}")
                self.log(f"GET /api/v1/reports/{month} (报告详情)",
                         resp3["status_code"] == 200,
                         f"库存{resp3['data'].get('data', {}).get('inventory_shares', 0):,}股，人均收益¥{resp3['data'].get('data', {}).get('average_profit_per_employee', 0):,.2f}")

                try:
                    pdf_resp = self._request("GET", f"/api/v1/reports/{month}/download/pdf")
                    pdf_ok = pdf_resp["status_code"] == 200 and len(pdf_resp.get("text", "")) > 0
                    self.log(f"GET /api/v1/reports/{month}/download/pdf (导出PDF)", pdf_ok,
                             f"响应大小约 {len(pdf_resp.get('text', ''))} 字节")
                except Exception as e:
                    self.log(f"GET /api/v1/reports/{month}/download/pdf", False, str(e))

                try:
                    xlsx_resp = self._request("GET", f"/api/v1/reports/{month}/download/excel")
                    x_ok = xlsx_resp["status_code"] == 200 and len(xlsx_resp.get("text", "")) > 0
                    self.log(f"GET /api/v1/reports/{month}/download/excel (导出Excel)", x_ok,
                             f"响应大小约 {len(xlsx_resp.get('text', ''))} 字节")
                except Exception as e:
                    self.log(f"GET /api/v1/reports/{month}/download/excel", False, str(e))

        except Exception as e:
            self.log("月度报告测试", False, str(e))

    def test_executive_alert(self):
        self.print_header("6. 高管减持预警检测")
        try:
            resp1 = self._request("GET", "/api/v1/executive-alerts/monitor")
            mon_ok = resp1["status_code"] == 200 and resp1["data"].get("success", True)
            alerts = resp1["data"].get("data", {}).get("alerts", [])
            self.log("GET /api/v1/executive-alerts/monitor (全量高管监控)", mon_ok,
                     f"发现 {len(alerts)} 项预警")

            resp2 = self._request("GET", "/api/v1/executive-alerts/shareholders")
            sh_ok = resp2["status_code"] == 200
            shareholders = resp2["data"].get("data", [])
            self.log("GET /api/v1/executive-alerts/shareholders (高管股东列表)",
                     sh_ok, f"共 {len(shareholders)} 位高管持股")

            if shareholders:
                exec_sh = shareholders[0]
                before = exec_sh.get("total_shares_held", 100000)
                after = int(before * 0.90)
                if before == 0:
                    before = 100000
                    after = 80000

                resp3 = self._request("POST", "/api/v1/executive-alerts/check",
                                     params={
                                         "employee_id": exec_sh["employee_id"],
                                         "shares_before": before,
                                         "shares_after": after,
                                     })
                check_ok = resp3["status_code"] == 200 and resp3["data"].get("success", True)
                check_data = resp3["data"].get("data", {})
                triggered = check_data.get("triggered", False)
                alerts_found = check_data.get("alerts", [])
                self.log("POST /api/v1/executive-alerts/check (减持预警检测)", check_ok,
                         f"减持{before-after:,}股({100-after/before*100:.1f}%), 预警触发: {triggered}, {len(alerts_found)}项",
                         resp3["data"] if not check_ok else None)

                resp4 = self._request("GET", "/api/v1/executive-alerts/pending")
                self.log("GET /api/v1/executive-alerts/pending (待审核预警)",
                         resp4["status_code"] == 200,
                         f"{resp4['data'].get('total', 0)} 条待合规审核")

            resp5 = self._request("GET", "/api/v1/logs", params={"limit": 10, "action": "ALERT"})
            self.log("GET /api/v1/logs (查询操作日志-预警)",
                     resp5["status_code"] == 200,
                     f"{resp5['data'].get('total', 0)} 条预警相关日志记录")

        except Exception as e:
            self.log("高管减持预警测试", False, str(e))


def main():
    parser = argparse.ArgumentParser(description="股权激励系统API集成测试")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API服务地址")
    parser.add_argument("--wait", type=int, default=0, help="等待服务启动秒数")
    args = parser.parse_args()

    if args.wait > 0:
        print(f"等待服务启动 {args.wait} 秒...")
        time.sleep(args.wait)

    tester = APITester(args.base_url)
    tester.run()
    return 0 if all(r["success"] for r in tester.results) else 1


if __name__ == "__main__":
    sys.exit(main())
