from app.parsers.seller_video_parser import SELLER_VIDEO_COMPLETION_DATA_TYPE

SELLER_ORDER_PATH = "/api/fulfillment/na/order/list"
SELLER_EXPORT_DOWNLOAD_PATH = "/api/fulfillment/na/order/download"
SELLER_EXPORT_FILE_PREFIX = "/easesafe/oec_trade_order_export/object/"
SELLER_VIDEO_COMPLETION_PATH = (
    "/api/v1/insights/seller/shop/video/diagnosis/video_second_trend"
)
MAX_EXPORT_BYTES = 25 * 1024 * 1024
RAW_ONLY_PATHS = {
    "/api/v3/insights/seller/ttp/product/list": "seller_product_analytics",
    "/api/v1/insights/seller/shop/live/list": "seller_live_analytics",
    "/api/v1/insights/seller/shop/live/stats": "seller_live_analytics_overview",
    "/api/v2/insights/seller/shop/video/analytics/video/list": (
        "seller_video_analytics"
    ),
    "/api/v1/insights/seller/shop/video/analytics/video/stats": (
        "seller_video_analytics_overview"
    ),
    "/api/v1/seller/growth_center/related_creator/get": "seller_creator_analytics",
    SELLER_VIDEO_COMPLETION_PATH: SELLER_VIDEO_COMPLETION_DATA_TYPE,
}
