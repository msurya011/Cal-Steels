"""Main APIRouter that aggregates all v1 routers."""
from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.projects import router as projects_router
from app.api.v1.drawings import router as drawings_router
from app.api.v1.members import router as members_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.bom import router as bom_router
from app.api.v1.config_router import router as config_router
from app.api.v1.model import router as model_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.events import router as events_router
from app.api.v1.sections import router as sections_router
from app.api.v1.exports import router as exports_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth_router)
api_router.include_router(projects_router)
api_router.include_router(drawings_router)
api_router.include_router(members_router)
api_router.include_router(jobs_router)
api_router.include_router(bom_router)
api_router.include_router(config_router)
api_router.include_router(model_router)
api_router.include_router(notifications_router)
api_router.include_router(events_router)
api_router.include_router(sections_router)
api_router.include_router(exports_router)
