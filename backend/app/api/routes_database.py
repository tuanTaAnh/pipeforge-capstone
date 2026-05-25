from fastapi import APIRouter

from app.services.database_graph_builder import build_database_graph

router = APIRouter(prefix="/api/database", tags=["database"])


@router.get("/graph")
async def get_database_graph() -> dict:
    return build_database_graph()
