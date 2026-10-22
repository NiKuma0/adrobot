from fastapi import APIRouter

from app.adapters.web.dependencies import (
    CreatorDep,
    DirectoryDep,
    EditorDep,
    OfferCatalogDep,
)
from app.adapters.web.schemas import (
    CampaignCreate,
    CampaignOut,
    FormOptionsOut,
    OfferAdd,
    OfferOut,
    PinRequest,
    StreamOut,
    TrackerCampaignOut,
)

router = APIRouter(prefix="/api")


@router.get("/offers", response_model=list[OfferOut])
async def offers(catalog: OfferCatalogDep, q: str = ""):
    return await catalog.search(q)


@router.get("/meta", response_model=FormOptionsOut)
async def meta(directory: DirectoryDep):
    """Groups, traffic sources and domains for the "new campaign" form."""
    return await directory.campaign_form_options()


@router.get("/keitaro/campaigns", response_model=list[TrackerCampaignOut])
async def keitaro_campaigns(directory: DirectoryDep):
    return await directory.campaigns()


@router.post("/campaigns", response_model=CampaignOut)
async def create_campaign(data: CampaignCreate, creator: CreatorDep):
    return await creator.create(**data.model_dump())


@router.get("/campaigns/{keitaro_id}", response_model=CampaignOut)
async def get_campaign(keitaro_id: int, editor: EditorDep):
    return await editor.get_campaign(keitaro_id)


@router.post("/campaigns/{keitaro_id}/fetch", response_model=CampaignOut)
async def fetch_streams(keitaro_id: int, editor: EditorDep):
    return await editor.import_campaign(keitaro_id)


@router.post("/streams/{stream_id}/offers", response_model=StreamOut)
async def add_offer(stream_id: int, data: OfferAdd, editor: EditorDep):
    return await editor.add_offer(stream_id, data.offer_id)


@router.post("/streams/{stream_id}/publish", response_model=StreamOut)
async def publish(stream_id: int, editor: EditorDep):
    return await editor.publish_stream(stream_id)


@router.post("/streams/{stream_id}/cancel", response_model=StreamOut)
async def cancel(stream_id: int, editor: EditorDep):
    return await editor.cancel_stream(stream_id)


@router.post("/stream-offers/{so_id}/remove", response_model=StreamOut)
async def remove_offer(so_id: int, editor: EditorDep):
    return await editor.remove_offer(so_id)


@router.post("/stream-offers/{so_id}/bring-back", response_model=StreamOut)
async def bring_back(so_id: int, editor: EditorDep):
    return await editor.bring_back_offer(so_id)


@router.post("/stream-offers/{so_id}/pin", response_model=StreamOut)
async def pin(so_id: int, data: PinRequest, editor: EditorDep):
    return await editor.pin_offer(so_id, data.pinned)
