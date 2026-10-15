from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class DashboardShopOption(BaseModel):
    id: str
    name: str
    platform: str
    site: str | None = None
    currency: str | None = None
    timezone: str | None = None


class DashboardFilterOptions(BaseModel):
    platforms: list[str]
    sites: list[str]
    shops: list[DashboardShopOption]
    currencies: list[str]


class DashboardSelection(BaseModel):
    platform: str | None = None
    site: str | None = None
    shopId: str | None = None
    currency: str
    timezone: str
    realtimeRange: Literal["today", "last24h"]
    trendRange: Literal["last7d", "last30d", "lastMonth", "year"]
    orderRange: Literal["last7d", "last14d", "last28d"]


class DashboardPeriod(BaseModel):
    start: datetime
    end: datetime


class DashboardSummary(BaseModel):
    salesVolume: int = Field(ge=0)
    orderCount: int = Field(ge=0)
    salesAmountMinor: int
    netSalesAmountMinor: int
    averageItemPriceMinor: int
    cancelledOrderCount: int = Field(ge=0)


class RealtimeSection(BaseModel):
    period: DashboardPeriod
    current: DashboardSummary
    previous: DashboardSummary
    lastWeek: DashboardSummary


class DashboardTrendPoint(BaseModel):
    date: str
    orderCount: int
    salesVolume: int
    salesAmountMinor: int
    netSalesAmountMinor: int


class TrendSection(BaseModel):
    period: DashboardPeriod
    current: DashboardSummary
    previous: DashboardSummary
    lastYear: DashboardSummary
    points: list[DashboardTrendPoint]


class DashboardDistributionItem(BaseModel):
    key: str
    orderCount: int
    salesVolume: int
    salesAmountMinor: int


class DashboardLabelMetric(BaseModel):
    label: str
    value: int


class DashboardProductPerformance(BaseModel):
    name: str
    sku: str
    productId: str
    platform: str
    store: str
    imageUrl: str | None = None
    salesVolume: int
    salesAmountMinor: int
    netSalesAmountMinor: int


class DashboardSampleFunnel(BaseModel):
    scope: Literal["current_projection_all_time"]
    applicationCount: int = Field(ge=0)
    approvedCount: int = Field(ge=0)
    shippedCount: int = Field(ge=0)
    completedCount: int = Field(ge=0)
    cancelledCount: int = Field(ge=0)
    sourceObservedAt: datetime | None = None


class DashboardCreatorLevel(BaseModel):
    level: Literal["L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7"]
    count: int = Field(ge=0)
    share: float = Field(ge=0, le=100)


class DashboardCreatorEfficiencyRow(BaseModel):
    id: str
    rank: int = Field(ge=1)
    username: str
    avatarUrl: str | None = None
    shopName: str
    videoCount: int = Field(ge=0)
    gmvMinor: int = Field(ge=0)
    gmvPerVideoMinor: int = Field(ge=0)
    sampleStatus: str | None = None
    cumulativeGmvShare: float = Field(ge=0, le=100)


class DashboardParetoPoint(BaseModel):
    id: str
    username: str
    shopName: str
    gmvMinor: int = Field(ge=0)
    cumulativeGmvShare: float = Field(ge=0, le=100)


class DashboardCreatorEfficiency(BaseModel):
    period: dict[str, date] | None = None
    complete: bool
    shopCount: int = Field(ge=0)
    totalCreators: int = Field(ge=0)
    totalGmvMinor: int = Field(ge=0)
    rows: list[DashboardCreatorEfficiencyRow]
    pareto: list[DashboardParetoPoint]


class DashboardAffiliateOperations(BaseModel):
    sampleFunnel: DashboardSampleFunnel
    creatorLevels: list[DashboardCreatorLevel]
    creatorEfficiency: DashboardCreatorEfficiency


class DashboardSnapshotResponse(BaseModel):
    generatedAt: datetime
    filters: DashboardFilterOptions
    selection: DashboardSelection
    realtime: RealtimeSection
    trend: TrendSection
    fulfilmentMetrics: list[DashboardLabelMetric]
    salesDistribution: list[DashboardDistributionItem]
    orderDistribution: list[DashboardDistributionItem]
    productPerformance: list[DashboardProductPerformance]
    affiliateOperations: DashboardAffiliateOperations
    netSalesEstimated: bool = True
