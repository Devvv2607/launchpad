from fastapi import APIRouter

from launchpad.api.v1 import assets, auth, meta, workspaces

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(meta.router)
api_router.include_router(auth.router)
api_router.include_router(workspaces.router)
api_router.include_router(assets.router)
