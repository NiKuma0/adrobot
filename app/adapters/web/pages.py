from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

STATIC = Path(__file__).parents[2] / "static"

router = APIRouter(include_in_schema=False)


@router.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@router.get("/campaigns/{keitaro_id}")
async def campaign_page(keitaro_id: int):
    return FileResponse(STATIC / "campaign.html")
