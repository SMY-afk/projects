from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID, uuid4

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from erp_api.infrastructure.database import Database
from erp_api.models.product import Product
from erp_api.models.product_sku import ProductSku
from erp_api.models.product_sync_run import ProductSyncRun
from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.services.media_image_repository import resolve_product_images
from erp_api.services.tiktok_client import TikTokTokenSet
from erp_api.services.tiktok_schemas import TikTokProduct, TikTokSku
from erp_api.services.token_cipher import TokenCipher


@dataclass(frozen=True)
class AuthorizedTikTokShop:
    id: UUID
    platform_shop_id: str
    access_token: str
    shop_cipher: str | None
    refresh_token: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class ProductSyncResult:
    run_id: UUID
    shop_id: UUID
    status: str
    fetched_count: int
    upserted_count: int
    last_cursor: str | None
    error: str | None


@dataclass(frozen=True)
class ProductListRecord:
    shop_id: UUID
    platform_product_id: str
    skus: list[dict[str, object]]
    name: str
    code: str
    status: str
    category: str
    stock: int
    updated_at: datetime
    shop_name: str
    current_price: str | None
    image_url: str | None


@dataclass(frozen=True)
class ProductListPage:
    items: list[ProductListRecord]
    total: int


def _stored_skus_from_payload(
    payload: dict[str, object] | None,
) -> list[dict[str, object]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("skus"), list):
        return []
    result: list[dict[str, object]] = []
    for raw in payload["skus"]:
        if not isinstance(raw, dict):
            continue
        platform_id = raw.get("platform_sku_id") or raw.get("sku_id") or raw.get("id")
        if not isinstance(platform_id, str) or not platform_id:
            continue
        seller_sku = raw.get("seller_sku") or raw.get("sellerSku") or platform_id
        try:
            price_minor = int(
                Decimal(str(raw.get("price_amount") or raw.get("price") or "0")) * 100
            )
        except (InvalidOperation, ValueError):
            price_minor = 0
        result.append(
            {
                "id": uuid4(),
                "platformSkuId": platform_id,
                "sellerSku": str(seller_sku),
                "stock": max(
                    0, int(raw.get("inventory_quantity") or raw.get("stock") or 0)
                ),
                "priceMinor": price_minor,
                "currency": str(raw.get("currency") or "USD").upper()[:3],
            }
        )
    return result


class ProductRepository:
    def __init__(self, database: Database, token_cipher: TokenCipher) -> None:
        self._database = database
        self._token_cipher = token_cipher

    async def get_authorized_tiktok_shop(
        self, tenant_id: UUID, shop_id: UUID
    ) -> AuthorizedTikTokShop | None:
        async for session in self._database.session(tenant_id):
            row = (
                await session.execute(
                    select(
                        Shop.id,
                        Shop.platform_shop_id,
                        ShopConnection.access_token_ciphertext,
                        ShopConnection.refresh_token_ciphertext,
                        ShopConnection.shop_ciphertext,
                        ShopConnection.expires_at,
                    )
                    .join(ShopConnection, ShopConnection.shop_id == Shop.id)
                    .where(
                        Shop.platform == "tiktok",
                        Shop.status == "active",
                        ShopConnection.auth_status == "authorized",
                        ShopConnection.access_token_ciphertext.is_not(None),
                        Shop.id == shop_id,
                    )
                    .order_by(Shop.created_at.desc())
                    .limit(1)
                )
            ).one_or_none()
            if row is None or row.access_token_ciphertext is None:
                return None
            return AuthorizedTikTokShop(
                id=row.id,
                platform_shop_id=row.platform_shop_id,
                access_token=self._token_cipher.decrypt(row.access_token_ciphertext),
                shop_cipher=(
                    self._token_cipher.decrypt(row.shop_ciphertext)
                    if row.shop_ciphertext
                    else None
                ),
                refresh_token=(
                    self._token_cipher.decrypt(row.refresh_token_ciphertext)
                    if row.refresh_token_ciphertext
                    else None
                ),
                expires_at=row.expires_at,
            )
        return None

    async def update_connection_tokens(
        self, tenant_id: UUID, shop_id: UUID, tokens: TikTokTokenSet
    ) -> bool:
        expires_at = (
            datetime.now(UTC) + timedelta(seconds=tokens.expires_in)
            if tokens.expires_in
            else None
        )
        async for session in self._database.session(tenant_id):
            result = await session.execute(
                update(ShopConnection)
                .where(
                    ShopConnection.shop_id == shop_id,
                    ShopConnection.auth_status == "authorized",
                )
                .values(
                    access_token_ciphertext=self._token_cipher.encrypt(
                        tokens.access_token
                    ),
                    refresh_token_ciphertext=(
                        self._token_cipher.encrypt(tokens.refresh_token)
                        if tokens.refresh_token
                        else ShopConnection.refresh_token_ciphertext
                    ),
                    expires_at=expires_at,
                    scopes=tokens.scopes,
                    last_error=None,
                )
            )
            await session.commit()
            return result.rowcount == 1
        return False

    async def list_products(
        self,
        tenant_id: UUID,
        *,
        page: int,
        page_size: int,
        keyword: str | None = None,
        status: str | None = None,
        shop_id: UUID | None = None,
    ) -> ProductListPage:
        async for session in self._database.session(tenant_id):
            rows = (
                await session.execute(
                    self._product_list_statement(
                        tenant_id=tenant_id,
                        keyword=keyword,
                        status=status,
                        shop_id=shop_id,
                        page=page,
                        page_size=page_size,
                    )
                )
            ).all()
            total = await session.scalar(
                self._product_count_statement(
                    tenant_id=tenant_id, keyword=keyword, status=status, shop_id=shop_id
                )
            )
            records: list[ProductListRecord] = []
            image_urls: dict[str, str] = {}
            for current_shop_id in {item.shop_id for item, _ in rows}:
                image_urls.update(
                    await resolve_product_images(
                        session,
                        current_shop_id,
                        (
                            item.platform_product_id
                            for item, _ in rows
                            if item.shop_id == current_shop_id
                        ),
                    )
                )
            for item, shop_name in rows:
                skus = [
                    {
                        "id": sku.id,
                        "platformSkuId": sku.platform_sku_id,
                        "sellerSku": sku.name,
                        "stock": sku.stock,
                        "priceMinor": sku.price_minor,
                        "currency": sku.currency,
                    }
                    for sku in item.skus
                ] or _stored_skus_from_payload(item.raw_payload)
                records.append(
                    ProductListRecord(
                        shop_id=item.shop_id,
                        platform_product_id=item.platform_product_id,
                        skus=skus,
                        name=item.name,
                        code=item.code,
                        status=item.status,
                        category=item.category,
                        stock=item.stock,
                        updated_at=item.updated_at,
                        shop_name=shop_name,
                        current_price=format_current_price(skus),
                        image_url=image_urls.get(item.platform_product_id),
                    )
                )
            return ProductListPage(
                items=records,
                total=total or 0,
            )
        raise RuntimeError("Tenant database session was not created.")

    @staticmethod
    def _product_filters(
        keyword: str | None, status: str | None, shop_id: UUID | None = None
    ):
        conditions = [
            Shop.platform == "tiktok",
            Shop.status == "active",
            ShopConnection.auth_status == "authorized",
        ]
        if shop_id is not None:
            conditions.append(Product.shop_id == shop_id)
        if keyword and (needle := keyword.strip()):
            pattern = f"%{needle}%"
            sku_match = exists(
                select(ProductSku.id).where(
                    ProductSku.product_id == Product.id,
                    or_(
                        ProductSku.platform_sku_id.ilike(pattern),
                        ProductSku.name.ilike(pattern),
                    ),
                )
            )
            conditions.append(
                or_(
                    Product.name.ilike(pattern),
                    Product.code.ilike(pattern),
                    Product.platform_product_id.ilike(pattern),
                    sku_match,
                )
            )
        if status:
            conditions.append(Product.status == status)
        return conditions

    @classmethod
    def _product_list_statement(
        cls,
        *,
        tenant_id: UUID,
        keyword: str | None,
        status: str | None,
        shop_id: UUID | None = None,
        page: int,
        page_size: int,
    ):
        return (
            select(Product, Shop.shop_name)
            .options(selectinload(Product.skus))
            .join(Shop, Shop.id == Product.shop_id)
            .join(ShopConnection, ShopConnection.shop_id == Shop.id)
            .where(
                Product.tenant_id == tenant_id,
                *cls._product_filters(keyword, status, shop_id),
            )
            .order_by(Product.updated_at.desc(), Product.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

    @classmethod
    def _product_count_statement(
        cls,
        *,
        tenant_id: UUID,
        keyword: str | None,
        status: str | None,
        shop_id: UUID | None = None,
    ):
        return (
            select(func.count())
            .select_from(Product)
            .join(Shop, Shop.id == Product.shop_id)
            .join(ShopConnection, ShopConnection.shop_id == Shop.id)
            .where(
                Product.tenant_id == tenant_id,
                *cls._product_filters(keyword, status, shop_id),
            )
        )

    async def create_sync_run(self, tenant_id: UUID, shop_id: UUID) -> UUID:
        async for session in self._database.session(tenant_id):
            run = ProductSyncRun(tenant_id=tenant_id, shop_id=shop_id, status="running")
            session.add(run)
            await session.commit()
            return run.id
        raise RuntimeError("Tenant database session was not created.")

    async def upsert_product_page(
        self,
        tenant_id: UUID,
        run_id: UUID,
        shop_id: UUID,
        products: list[TikTokProduct],
        next_cursor: str,
    ) -> int:
        async for session in self._database.session(tenant_id):
            for product in products:
                product_id = await session.scalar(
                    self._product_upsert(tenant_id, shop_id, product)
                )
                if product_id is None:
                    raise RuntimeError("Product upsert did not return an identifier.")
                await self._sync_skus(session, tenant_id, product_id, product.skus)
            await session.execute(
                update(ProductSyncRun)
                .where(ProductSyncRun.id == run_id, ProductSyncRun.shop_id == shop_id)
                .values(
                    fetched_count=ProductSyncRun.fetched_count + len(products),
                    upserted_count=ProductSyncRun.upserted_count + len(products),
                    last_cursor=next_cursor,
                )
            )
            await session.commit()
            return len(products)
        raise RuntimeError("Tenant database session was not created.")

    async def complete_sync_run(
        self, tenant_id: UUID, run_id: UUID
    ) -> ProductSyncResult:
        return await self._finish_run(tenant_id, run_id, status="succeeded", error=None)

    async def fail_sync_run(
        self, tenant_id: UUID, run_id: UUID, error: str
    ) -> ProductSyncResult:
        return await self._finish_run(tenant_id, run_id, status="failed", error=error)

    async def _finish_run(
        self, tenant_id: UUID, run_id: UUID, *, status: str, error: str | None
    ) -> ProductSyncResult:
        async for session in self._database.session(tenant_id):
            await session.execute(
                update(ProductSyncRun)
                .where(ProductSyncRun.id == run_id)
                .values(status=status, error=error, finished_at=datetime.now(UTC))
            )
            await session.commit()
            run = await session.get(ProductSyncRun, run_id)
            if run is None:
                raise RuntimeError("Product sync run was not found.")
            return ProductSyncResult(
                run_id=run.id,
                shop_id=run.shop_id,
                status=run.status,
                fetched_count=run.fetched_count,
                upserted_count=run.upserted_count,
                last_cursor=run.last_cursor,
                error=run.error,
            )
        raise RuntimeError("Tenant database session was not created.")

    @staticmethod
    def _product_upsert(tenant_id: UUID, shop_id: UUID, product: TikTokProduct):
        stock = sum(max(0, sku.inventory_quantity or 0) for sku in product.skus)
        seller_code = next(
            (sku.seller_sku for sku in product.skus if sku.seller_sku), None
        )
        product_code = seller_code or (
            product.skus[0].platform_sku_id
            if product.skus
            else product.platform_product_id
        )
        raw_payload = getattr(product, "raw_payload", None) or asdict(product)
        statement = insert(Product).values(
            tenant_id=tenant_id,
            shop_id=shop_id,
            platform_product_id=_bounded(product.platform_product_id, 128),
            name=_bounded(product.name, 200),
            code=_bounded(product_code, 100),
            status=_bounded(product.status or "active", 32),
            category=_bounded(
                product.sales_regions[0] if product.sales_regions else "-", 200
            ),
            stock=stock,
            raw_payload=raw_payload,
        )
        return statement.on_conflict_do_update(
            constraint="uq_products_shop_platform_product",
            set_={
                "name": statement.excluded.name,
                "code": statement.excluded.code,
                "status": statement.excluded.status,
                "category": statement.excluded.category,
                "stock": statement.excluded.stock,
                "raw_payload": statement.excluded.raw_payload,
                "updated_at": datetime.now(UTC),
            },
        ).returning(Product.id)

    @staticmethod
    async def _sync_skus(
        session, tenant_id: UUID, product_id: UUID, skus: list[TikTokSku]
    ) -> None:
        sku_ids = [sku.platform_sku_id for sku in skus]
        stale = delete(ProductSku).where(ProductSku.product_id == product_id)
        if sku_ids:
            stale = stale.where(ProductSku.platform_sku_id.not_in(sku_ids))
        await session.execute(stale)
        for sku in skus:
            statement = insert(ProductSku).values(
                tenant_id=tenant_id,
                product_id=product_id,
                platform_sku_id=_bounded(sku.platform_sku_id, 128),
                name=_bounded(sku.seller_sku or sku.platform_sku_id, 200),
                price_minor=_price_minor(sku.price_amount),
                currency=(sku.currency or "USD").upper()[:3],
                stock=max(0, sku.inventory_quantity or 0),
            )
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_product_skus_product_platform_sku",
                    set_={
                        "name": statement.excluded.name,
                        "price_minor": statement.excluded.price_minor,
                        "currency": statement.excluded.currency,
                        "stock": statement.excluded.stock,
                    },
                )
            )


def _price_minor(amount: str | None) -> int:
    if not amount:
        return 0
    try:
        return int((Decimal(amount) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except InvalidOperation as error:
        raise ValueError("TikTok SKU price is invalid.") from error


def format_current_price(skus: list[dict[str, object]]) -> str | None:
    prices = [
        (int(sku["priceMinor"]), str(sku.get("currency") or "USD").upper()[:3])
        for sku in skus
        if isinstance(sku.get("priceMinor"), int) and int(sku["priceMinor"]) > 0
    ]
    if not prices:
        return None
    currencies = {currency for _, currency in prices}
    if len(currencies) == 1:
        currency = next(iter(currencies))
        values = sorted({minor for minor, _ in prices})
        formatted = [f"{minor / 100:.2f}" for minor in values]
        return (
            f"{currency} {formatted[0]}"
            if len(formatted) == 1
            else f"{currency} {formatted[0]} - {formatted[-1]}"
        )
    return ", ".join(f"{currency} {minor / 100:.2f}" for minor, currency in prices)


def _bounded(value: str, max_length: int) -> str:
    return value[:max_length]
