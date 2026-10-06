from fastapi import APIRouter

from launchpad.api.v1 import agent, ai, assets, auth, brand, content, meta, workspaces

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(meta.router)
api_router.include_router(auth.router)
api_router.include_router(workspaces.router)
api_router.include_router(assets.router)
api_router.include_router(brand.router)
api_router.include_router(content.router)
api_router.include_router(ai.router)
api_router.include_router(agent.router)
