# TikTok Shop 内容发布 API 版本矩阵

基线日期：2026-08-21。矩阵只采用 TikTok Shop Partner Center 官方文档；“已冻结”表示方法、路径、版本和主要输入输出均可进入实现，“待冻结”表示禁止据此实现真实发布。

| 能力           | 方法与官方路径                                                                                                | 当前版本     | Gate 0 结论               | ERP 实现约束                                                                            |
| -------------- | ------------------------------------------------------------------------------------------------------------- | ------------ | ------------------------- | --------------------------------------------------------------------------------------- |
| 创作者授权     | Creator Authorization Guide（OAuth v2）                                                                       | v2           | 待创作者授权              | token 响应必须同时校验 `code=0`、`user_type=1`、`open_id`、`granted_scopes`             |
| 获取创作者资料 | `GET /affiliate_creator/202508/profiles`                                                                      | 202508       | 已冻结；未获权            | 只读探针已实现，不落原始资料                                                            |
| 获取橱窗商品   | `GET /affiliate_creator/202405/showcases/products`                                                            | 202405       | 已冻结；未获权            | `page_size` 1–20，最多读取 2,000 个商品                                                 |
| 添加橱窗商品   | `POST /affiliate_creator/202405/showcases/products`                                                           | 202405       | 已冻结；未获权            | 属于写操作，Gate 0 不执行                                                               |
| 直接上传视频   | `POST /affiliate_creator/202505/videos/video_files`                                                           | 202505       | 已冻结；未获权            | multipart，直接上传上限 100 MB                                                          |
| 大文件上传     | `POST /open/202512/file/init` 及分片流程                                                                      | 202512       | 已冻结；未获权            | 文件超过 10 MB 使用分片；可发布视频上限 500 MB                                          |
| 视频内容预检   | `POST /affiliate_creator/202511/videos/precheck_task`                                                         | 202511       | 已冻结；未获权            | 发布前必经；保存任务 ID，不保存完整敏感响应                                             |
| 查询预检结果   | `GET /affiliate_creator/202511/videos/precheck_tasks/{task_id}`                                               | 202511       | 已冻结；未获权            | 轮询需要退避和终止条件                                                                  |
| 发布挂车视频   | 官方变更日志已发布 Post Shoppable Video v202607；可读的旧 API Page 为 `POST /affiliate_creator/202603/videos` | 202607       | **待冻结**                | 不得按旧版 202603 开发真实发布；需在当前应用 API Page/API Testing Tool 固化 202607 字段 |
| 发布挂车图片   | 官方变更日志已发布 Post Shoppable Photos v202607                                                              | 202607       | **待冻结**                | 当前公开页面未稳定暴露精确路径和 schema，禁止猜测实现                                   |
| 查询视频状态   | `GET /affiliate_creator/202509/videos/{video_id}/status`                                                      | 202509       | 已冻结；未获权            | 用于平台状态回写，不用本地提交状态代替                                                  |
| 创作者视频表现 | `GET /analytics/202403/videos/performances`                                                                   | 202403       | 已冻结；未获权            | 仅美国创作者；最多 100 个同一作者视频 ID；数据 T-1、窗口 180 天                         |
| 店铺视频表现   | `GET /analytics/202605/shop_videos/performance`                                                               | 202605       | 已冻结；卖家 Scope 已具备 | 卖家令牌，`page_size<=100`，数据 T-1                                                    |
| 店铺视频概览   | `GET /analytics/202509/shop_videos/overview_performance`                                                      | 202509       | 已冻结；卖家 Scope 已具备 | 用于概览 KPI，不替代内容明细                                                            |
| 内容发布事件   | Event type 17: Shoppable content posting                                                                      | 当前事件协议 | 已冻结；未获权            | 覆盖 add/update/remove；Webhook 验签、幂等、乱序处理                                    |

## 版本冻结规则

1. 发布接口的版本以当前 Partner Center 应用中可见的 API Page 和 API Testing Tool 为准，不能只依据搜索摘要或旧文档。
2. 路径版本、请求字段、枚举、Scope、市场限制任一变化，都要更新本矩阵和契约测试。
3. 读取接口可独立交付；`202607` 发布契约未冻结前，真实发布开关必须保持关闭。
4. ERP 内部接口版本与 TikTok 上游版本解耦，由后端适配层统一转换。

## 官方依据

- [Creator Authorization Guide](https://partner.tiktokshop.com/docv2/page/creator-authorization-guide)
- [TikTok Shop API Changelog](https://partner.tiktokshop.com/docv2/changelog)
- [Get Creator Profile](https://partner.tiktokshop.com/docv2/page/get-creator-profile)
- [Get Showcase Products](https://partner.tiktokshop.com/docv2/page/get-showcase-products)
- [Upload Shoppable Video File](https://partner.tiktokshop.com/docv2/page/upload-shoppable-video-file-202505)
- [Precheck Video Content](https://partner.tiktokshop.com/docv2/page/precheck-video-content-202511)
- [Get Shoppable Video Status](https://partner.tiktokshop.com/docv2/page/get-shoppable-video-status-202509)
- [Get Video Performances](https://partner.tiktokshop.com/docv2/page/get-video-performances-202403)
- [Shop Video Performance API update](https://partner.tiktokshop.com/docv2/page/kpkfccsa)
- [Get Shop Video Performance Overview](https://partner.tiktokshop.com/docv2/page/get-shop-video-performance-overview-202509)
- [Event type 17: Shoppable Content Posting](https://partner.tiktokshop.com/docv2/page/17-shoppable-content-posting)
