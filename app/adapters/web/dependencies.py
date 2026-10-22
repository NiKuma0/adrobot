"""Builds use cases per request from the container; one session (unit of work) per request."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.repository import CampaignRepository
from app.application.creator import CampaignCreator
from app.application.directory import TrackerDirectory
from app.application.editor import CampaignEditor
from app.application.offers import OfferCatalog
from app.container import Container


async def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


async def get_session(container: ContainerDep) -> AsyncIterator[AsyncSession]:
    # uncommitted changes are rolled back when the session closes
    async with container.session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_campaigns(session: SessionDep) -> CampaignRepository:
    return CampaignRepository(session)


CampaignsDep = Annotated[CampaignRepository, Depends(get_campaigns)]


async def get_offer_catalog(container: ContainerDep) -> OfferCatalog:
    return container.offers


OfferCatalogDep = Annotated[OfferCatalog, Depends(get_offer_catalog)]


async def get_directory(container: ContainerDep) -> TrackerDirectory:
    return TrackerDirectory(container.tracker, container.defaults)


DirectoryDep = Annotated[TrackerDirectory, Depends(get_directory)]


async def get_editor(session: SessionDep, campaigns: CampaignsDep, container: ContainerDep) -> CampaignEditor:
    return CampaignEditor(session, campaigns, container.tracker, container.offers)


EditorDep = Annotated[CampaignEditor, Depends(get_editor)]


async def get_creator(editor: EditorDep, container: ContainerDep) -> CampaignCreator:
    return CampaignCreator(container.tracker, editor, container.defaults)


CreatorDep = Annotated[CampaignCreator, Depends(get_creator)]
