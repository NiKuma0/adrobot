from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.adapters.web import api, pages
from app.adapters.web.errors import install_error_handlers
from app.config import CampaignSettings, DatabaseSettings, KeitaroSettings
from app.container import Container


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.container = Container.from_settings(KeitaroSettings(), DatabaseSettings(), CampaignSettings())
    yield
    await app.state.container.aclose()


app = FastAPI(title="Adrobot — Keitaro wrapper", lifespan=lifespan)
app.include_router(api.router)
app.include_router(pages.router)
install_error_handlers(app)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
