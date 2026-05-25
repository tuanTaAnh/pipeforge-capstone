from fastapi import FastAPI

from app.api.routes_answers import router as answers_router
from app.api.routes_artifacts import router as artifacts_router
from app.api.routes_database import router as database_router
from app.api.routes_health import router as health_router
from app.api.routes_runs import router as runs_router
from app.core.cors import setup_cors


def create_app() -> FastAPI:
    app = FastAPI(title="PipeForge Backend")

    setup_cors(app)

    app.include_router(health_router)
    app.include_router(runs_router)
    app.include_router(answers_router)
    app.include_router(artifacts_router)
    app.include_router(database_router)

    return app


app = create_app()