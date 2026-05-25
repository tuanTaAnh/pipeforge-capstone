from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.services.pipeline.pipeline_executor import (
    PipelineExecutionError,
    all_tables_zip_bytes,
    execute_pipeline,
    get_pipeline_status,
    preview_table,
    table_csv_bytes,
)
from app.services.runtime.run_registry import registry

router = APIRouter(prefix="/api/runs", tags=["pipeline"])


@router.get("/{run_id}/pipeline")
async def get_pipeline(run_id: str) -> dict:
    if not registry.exists(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    return get_pipeline_status(run_id)


@router.post("/{run_id}/pipeline/execute")
async def run_pipeline(run_id: str) -> dict:
    if not registry.exists(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        return execute_pipeline(run_id)
    except PipelineExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{run_id}/pipeline/tables/{table_name}/preview")
async def preview_pipeline_table(
    run_id: str,
    table_name: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    if not registry.exists(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        return preview_table(run_id, table_name, limit=limit)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{run_id}/pipeline/tables/{table_name}/download.csv")
async def download_pipeline_table_csv(run_id: str, table_name: str) -> Response:
    if not registry.exists(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        content = table_csv_bytes(run_id, table_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{table_name}.csv"'},
    )


@router.get("/{run_id}/pipeline/download.zip")
async def download_pipeline_csv_zip(run_id: str) -> Response:
    if not registry.exists(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    content = all_tables_zip_bytes(run_id)
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{run_id}_demo_mart_csv.zip"'},
    )
