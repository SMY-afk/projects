from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class RankingPeriod(BaseModel):
    start: date
    end: date


class TopVideo(BaseModel):
    id: str
    videoId: str
    shopName: str
    creatorUsername: str | None = None
    title: str | None = None
    coverImageUrl: str | None = None
    videoPostTime: datetime | None = None
    gmvMinor: int = Field(ge=0)
    views: int | None = None


class TopProduct(BaseModel):
    id: str
    productId: str
    shopName: str
    title: str | None = None
    coverImageUrl: str | None = None
    videoCount: int = Field(ge=0)
    singleProductVideoGmvMinor: int | None = Field(default=None, ge=0)
    singleProductVideoItemsSold: int | None = Field(default=None, ge=0)


class DashboardAffiliateRankingsResponse(BaseModel):
    period: RankingPeriod | None = None
    days: Literal[7, 30, 90]
    complete: bool
    shopCount: int = Field(ge=0)
    expectedShopCount: int = Field(ge=0)
    totalVideos: int = Field(ge=0)
    totalProducts: int = Field(ge=0)
    topVideos: list[TopVideo]
    topProducts: list[TopProduct]
    productMetricScope: Literal["single_product_videos_only"]
