from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api import api_router
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.bootstrap import ensure_bootstrap_admin
from app.services.file_pipeline import FilePipelineService


@asynccontextmanager
async def lifespan(app: FastAPI):
    with SessionLocal() as db:
        ensure_bootstrap_admin(db)
    pipeline = FilePipelineService()
    await pipeline.start()
    app.state.file_pipeline = pipeline
    yield
    await pipeline.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
    app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
    assets_dir = settings.web_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    if settings.logo_dir.exists():
        app.mount("/logo", StaticFiles(directory=str(settings.logo_dir)), name="logo")
    app.include_router(api_router)

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path.startswith("api") or full_path.startswith("assets") or full_path.startswith("logo"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        index_file = settings.web_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return JSONResponse(
            {
                "detail": "Frontend bundle not found. Build React app with `npm run build` in `frontend/`."
            },
            status_code=503,
        )

    return app


app = create_app()
