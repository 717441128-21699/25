import sys
sys.path.insert(0, '.')

print("=" * 60)
print("企业级员工股权激励管理系统 - 模块验证")
print("=" * 60)

modules = [
    ("config.settings", "配置模块"),
    ("database.connection", "数据库连接"),
    ("database.models", "数据模型"),
    ("utils.common", "通用工具"),
    ("utils.cache", "Redis缓存"),
    ("utils.logger", "日志模块"),
    ("utils.operation_log", "操作日志"),
    ("services.hr_sync", "HR同步服务"),
    ("services.equity_engine", "股权引擎"),
    ("services.shareholder", "股东名册服务"),
    ("services.exercise_service", "行权服务"),
    ("services.repurchase_service", "回购服务"),
    ("services.agreement_service", "协议服务"),
    ("services.executive_alert", "高管预警服务"),
    ("services.report_service", "报告服务"),
    ("schemas", "数据校验Schema"),
    ("api", "API路由"),
]

failed = []
passed = []

for module_path, desc in modules:
    try:
        __import__(module_path)
        passed.append(desc)
        print(f"  [OK]    {desc}")
    except Exception as e:
        failed.append((desc, str(e)))
        print(f"  [FAIL]  {desc}: {e}")

print()
print("=" * 60)
print(f"结果: {len(passed)}/{len(modules)} 模块通过验证")
print("=" * 60)

if failed:
    print()
    print("失败模块详情:")
    for desc, error in failed:
        print(f"  - {desc}: {error}")
    sys.exit(1)
else:
    print()
    print("所有模块验证通过！系统已准备就绪。")
    sys.exit(0)
