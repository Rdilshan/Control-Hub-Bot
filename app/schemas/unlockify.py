"""Unlockify Provider Pydantic Schemas."""

from typing import List, Optional
from pydantic import BaseModel, Field


class UnlockifyCreateLinkRequest(BaseModel):
    title: str = Field(..., description="The title of the video / unlock destination")
    advertisement_urls: List[str] = Field(..., description="List of sponsor / direct links")
    destination_url: str = Field(..., description="The platform destination URL to deliver after unlocking")


class UnlockifyLinkData(BaseModel):
    id: str = Field(..., description="Unique Unlockify link identifier")
    title: Optional[str] = None
    ads_count: Optional[int] = 1
    unlock_url: str = Field(..., description="The public unlock URL for viewers")


class UnlockifyCreateLinkResponse(BaseModel):
    success: bool
    data: Optional[UnlockifyLinkData] = None
    message: Optional[str] = None
