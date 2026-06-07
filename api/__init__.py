from fastapi import APIRouter
from .employees import router as employees_router
from .equity import router as equity_router
from .exercises import router as exercises_router
from .repurchases import router as repurchases_router
from .agreements import router as agreements_router
from .executive_alerts import router as executive_alerts_router
from .reports import router as reports_router
from .shareholders import router as shareholders_router
from .logs import router as logs_router

api_router = APIRouter()

api_router.include_router(employees_router)
api_router.include_router(equity_router)
api_router.include_router(exercises_router)
api_router.include_router(repurchases_router)
api_router.include_router(agreements_router)
api_router.include_router(executive_alerts_router)
api_router.include_router(reports_router)
api_router.include_router(shareholders_router)
api_router.include_router(logs_router)

__all__ = ["api_router"]
