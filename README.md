# 企业级员工股权激励自动化管理系统

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI API 服务层                         │
│  员工管理 | 激励计划 | 授予 | 行权 | 回购 | 协议 | 报告 | 预警 │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼───────────────┐
        ▼              ▼               ▼
  PostgreSQL 16      Redis 7       Celery Worker
  (业务数据持久化)   (缓存/锁/队列)   (异步任务/定时任务)
```

## 功能清单

| 模块 | 功能描述 |
|------|---------|
| **HR同步** | 自动从HR系统抓取员工信息，支持Mock数据快速初始化 |
| **激励计划** | 支持期权(OPTION)、限制性股票(RSU)、业绩股票(PSU)三种类型 |
| **授予引擎** | 基于员工级别+年薪公式计算，支持悬崖期+分期归属时间表 |
| **行权管理** | 实时校验、7级累进个税计算、个税递延政策、自动扣款 |
| **回购审批** | 4种回购原因定价，超100万需董事会，超500万需股东会 |
| **电子协议** | 自动生成、发送、签署、归档全流程 |
| **月度报告** | 自动生成6大指标、12个月趋势图，支持PDF+Excel双格式导出 |
| **高管预警** | 三重阈值监控，自动生成合规公告草稿待审核 |
| **审计日志** | 全量操作记录，支持多维度组合查询+批量导出(JSON/CSV) |
| **高并发** | Redis缓存、分布式锁、数据库连接池(50+100)、异步任务队列 |

## 快速启动

### 方式一：Docker Compose（推荐）

一键启动所有服务（PostgreSQL + Redis + FastAPI + Celery Worker + Celery Beat）

```bash
cd e:\solo\25

# 1. 构建并启动所有服务（后台运行）
docker-compose up -d --build

# 2. 查看服务状态
docker-compose ps

# 3. 查看API服务日志
docker-compose logs -f api

# 4. 等待约30秒后，运行API集成测试
python test_api.py --base-url http://localhost:8000 --wait 10

# 5. 停止服务
docker-compose down
```

启动成功后访问：
- **API文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/health

### 方式二：本地开发模式（SQLite + 内存缓存）

无需安装PostgreSQL和Redis，适合快速验证：

```bash
cd e:\solo\25

# 1. 安装依赖
pip install -r requirements.txt

# 2. 初始化数据库（自动创建表+Mock数据）
python init_data.py

# 3. 启动API服务
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 4. 新开终端，运行API测试
python test_api.py
```

## 核心API调用示例

所有接口基础路径：`http://localhost:8000/api/v1`

### 1. HR系统同步员工信息

```bash
# 触发HR同步（Mock模式自动生成200名员工）
curl -X POST http://localhost:8000/api/v1/employees/sync

# 查询员工列表
curl http://localhost:8000/api/v1/employees?limit=10
```

**Python调用:**
```python
import httpx
resp = httpx.post("http://localhost:8000/api/v1/employees/sync")
print(resp.json())
# 返回: {"success": true, "data": {"created": 200, "updated": 0, "total": 200}}
```

### 2. 创建激励计划并计算授予数量

```bash
# 创建股票期权激励计划
curl -X POST http://localhost:8000/api/v1/equity/plans \
  -H "Content-Type: application/json" \
  -d '{
    "plan_code": "OPT-TEST-001",
    "plan_name": "测试股票期权计划",
    "equity_type": "OPTION",
    "total_shares_reserved": 1000000,
    "effective_date": "2024-01-01",
    "expiration_date": "2034-01-01",
    "vesting_period_months": 48,
    "cliff_months": 12,
    "cliff_percentage": 0.25,
    "exercise_price_method": "FMV_GRANT_DATE"
  }'

# 计算授予数量
curl -X POST http://localhost:8000/api/v1/equity/grants/calculate \
  -H "Content-Type: application/json" \
  -d '{
    "employee_id": "EMP000001",
    "plan_code": "OPT-2024",
    "grant_date": "2025-01-15",
    "custom_shares": 50000
  }'

# 正式创建授予
curl -X POST http://localhost:8000/api/v1/equity/grants \
  -H "Content-Type: application/json" \
  -d '{
    "employee_id": "EMP000001",
    "plan_code": "OPT-2024",
    "grant_date": "2025-01-15",
    "custom_shares": 50000
  }'

# 查询当前股价
curl http://localhost:8000/api/v1/equity/stock-price/current
```

### 3. 员工行权申请并计算税款

```bash
# 第一步：先校验（计算税款）
curl -X POST http://localhost:8000/api/v1/exercises/validate \
  -H "Content-Type: application/json" \
  -d '{
    "employee_id": "EMP000001",
    "grant_id": "GR2025xxxxxxxxxx",
    "shares_to_exercise": 1000
  }'
# 返回会包含: estimated_tax（个税）、estimated_total_deduction（总扣款）

# 第二步：提交行权申请
curl -X POST http://localhost:8000/api/v1/exercises/apply \
  -H "Content-Type: application/json" \
  -d '{
    "employee_id": "EMP000001",
    "grant_id": "GR2025xxxxxxxxxx",
    "shares_to_exercise": 1000
  }'

# 第三步：审批并完成行权
curl -X POST "http://localhost:8000/api/v1/exercises/{request_id}/approve?approver_id=admin&approver_name=管理员"
```

### 4. 发起回购并触发多级审批

```bash
# 第一步：计算回购金额（系统自动判断需要的审批级别）
curl "http://localhost:8000/api/v1/repurchases/calculate?employee_id=EMP000001&reason_type=VOLUNTARY_TERMINATION"
# 返回中会包含: required_approval_levels: ["MANAGER", "BOARD"] (超100万自动包含董事会)

# 第二步：创建回购申请
curl -X POST "http://localhost:8000/api/v1/repurchases?initiated_by=admin&initiator_name=管理员" \
  -H "Content-Type: application/json" \
  -d '{
    "employee_id": "EMP000001",
    "reason_type": "VOLUNTARY_TERMINATION",
    "reason": "员工自愿离职"
  }'

# 第三步：提交审批
curl -X POST "http://localhost:8000/api/v1/repurchases/{request_id}/submit"

# 第四步：各级审批
# 经理级审批
curl -X POST "http://localhost:8000/api/v1/repurchases/{request_id}/approve" \
  -H "Content-Type: application/json" \
  -d '{"approval_level": "MANAGER", "comments": "同意"}'

# 董事会审批（超100万需此步骤）
curl -X POST "http://localhost:8000/api/v1/repurchases/{request_id}/approve" \
  -H "Content-Type: application/json" \
  -d '{"approval_level": "BOARD", "comments": "董事会审议通过", "vote_count": {"agree": 9, "disagree": 0, "abstain": 0}}'

# 股东会审批（超500万需此步骤）
curl -X POST "http://localhost:8000/api/v1/repurchases/{request_id}/approve" \
  -H "Content-Type: application/json" \
  -d '{"approval_level": "SHAREHOLDER", "comments": "股东会通过"}'

# 全部审批完成后执行回购
curl -X POST "http://localhost:8000/api/v1/repurchases/{request_id}/complete"
```

### 5. 生成月度报告并导出PDF/Excel

```bash
# 同步生成报告（较慢，建议生产用async_mode=true）
curl -X POST "http://localhost:8000/api/v1/reports/generate?report_month=2025-06&async_mode=false"

# 查看报告列表
curl http://localhost:8000/api/v1/reports

# 查看报告详情
curl http://localhost:8000/api/v1/reports/2025-06

# 下载PDF报告
curl -o report.pdf http://localhost:8000/api/v1/reports/2025-06/download/pdf

# 下载Excel报告
curl -o report.xlsx http://localhost:8000/api/v1/reports/2025-06/download/excel
```

### 6. 高管减持预警检测

```bash
# 全量监控高管持仓
curl http://localhost:8000/api/v1/executive-alerts/monitor

# 查看高管股东列表
curl http://localhost:8000/api/v1/executive-alerts/shareholders

# 模拟减持检测（减持10%触发预警）
curl -X POST "http://localhost:8000/api/v1/executive-alerts/check?employee_id=EMP000175&shares_before=100000&shares_after=90000"

# 查看待合规审核的预警
curl http://localhost:8000/api/v1/executive-alerts/pending

# 合规审核通过
curl -X POST "http://localhost:8000/api/v1/executive-alerts/{alert_id}/approve"
```

## 完整测试脚本

系统提供了 [test_api.py](file:///e:/solo/25/test_api.py) 一键测试脚本，覆盖全部6大核心接口：

```bash
python test_api.py

# 指定服务地址+等待启动时间
python test_api.py --base-url http://localhost:8000 --wait 15
```

脚本会输出带颜色的测试结果，类似：
```
  ✓ PASS POST /api/v1/employees/sync - 新增200人, 更新0人, 共200人
  ✓ PASS POST /api/v1/equity/plans (创建激励计划) - 计划代码=OPT-2024
  ✓ PASS POST /api/v1/exercises/validate (行权校验+税算) - 校验通过, 税额¥15,230.00
  ✓ PASS POST /api/v1/repurchases/calculate (回购计算) - 回购5,000股，金额¥425,000.00
  ✓ PASS POST /api/v1/reports/generate - 授予150,000股, 行权25,000股
  ✓ PASS GET /api/v1/executive-alerts/monitor (全量高管监控) - 发现 3 项预警

  总计: 35/35 通过 (100.0%)
```

## 审批阈值说明

| 回购总金额 | 所需审批级别 |
|-----------|-------------|
| < 100万元 | 经理级审批 |
| ≥ 100万元 | 经理级 + 董事会审批 |
| ≥ 500万元 | 经理级 + 董事会 + 股东会审批 |

## 个税计算规则

采用**7级超额累进税率**，支持**个税递延政策**（≤12万元免税额度）：

| 应纳税所得额 | 税率 | 速算扣除数 |
|-------------|------|-----------|
| ≤36,000 | 3% | 0 |
| 36,000-144,000 | 10% | 2,520 |
| 144,000-300,000 | 20% | 16,920 |
| 300,000-420,000 | 25% | 31,920 |
| 420,000-660,000 | 30% | 52,920 |
| 660,000-960,000 | 35% | 85,920 |
| >960,000 | 45% | 181,920 |

## 目录结构说明

```
e:\solo\25\
├── main.py                  # FastAPI主应用入口
├── init_data.py             # 数据库初始化+Mock数据脚本
├── validate.py              # 模块导入验证
├── test_api.py              # ★ API集成测试脚本
├── Dockerfile               # Docker镜像构建
├── docker-compose.yml       # ★ 一键启动编排
├── requirements.txt         # Python依赖
├── .env.example             # 环境变量模板
├── config/                  # 配置模块
├── database/                # 数据库层（连接+16个数据模型）
├── schemas/                 # Pydantic数据校验Schema
├── utils/                   # 工具（缓存/日志/审计）
├── services/                # 8大核心业务服务
├── tasks/                   # Celery异步任务+定时任务
└── api/                     # 9大模块RESTful接口
```

## 技术栈

| 类别 | 技术 | 说明 |
|------|------|------|
| Web框架 | FastAPI 0.104+ | 高性能异步，自动生成Swagger文档 |
| ORM | SQLAlchemy 2.0+ | 数据库连接池(50常驻+100溢出) |
| 数据库 | PostgreSQL 16 | 生产级关系型数据库 |
| 缓存 | Redis 7 | 分布式锁+热点数据缓存，不可用时自动降级内存缓存 |
| 异步任务 | Celery 5.3+ | 批量行权、报告生成、协议签署等 |
| 定时调度 | APScheduler + Celery Beat | HR同步、归属处理、月度报告 |
| 报告 | ReportLab + Pandas/openpyxl | PDF+Excel双格式导出 |
| 图表 | Matplotlib | 12个月同比趋势图 |
