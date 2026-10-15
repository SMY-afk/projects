# TikTok Shop 内容发布错误码矩阵

基线日期：2026-08-21。先按 `code` 判断业务错误，再保留 HTTP 状态、`request_id` 和发生阶段；对用户展示安全文案，原始平台 message 仅允许进入受控诊断日志。

| 错误码               | 来源/含义                                          | ERP 分类                     | 是否重试       | 建议动作                                             |
| -------------------- | -------------------------------------------------- | ---------------------------- | -------------- | ---------------------------------------------------- |
| `0`                  | 成功                                               | SUCCESS                      | 否             | 继续状态机                                           |
| `101000`             | token 与接口主体/授权对象不匹配                    | AUTH_SUBJECT_MISMATCH        | 否             | 重新走 Creator OAuth，校验 `user_type=1`             |
| `105001`             | token 无效或已撤销                                 | AUTH_INVALID                 | 否             | 清除连接可用态并重新授权                             |
| `105002`             | token 已过期                                       | AUTH_EXPIRED                 | 仅刷新一次     | 后端刷新；失败则重新授权                             |
| `105005`             | 应用或 token 缺少 Scope                            | SCOPE_MISSING                | 否             | 显示缺失 Scope，等待应用审核/重新授权                |
| `18001405`           | Creator 未选择 Region                              | MARKET_REGION_MISSING        | 否             | 在 Creator 授权流程完成 Selection Region             |
| `36009003`           | 平台内部错误                                       | PLATFORM_INTERNAL            | 是             | 指数退避，超过上限进入人工重试                       |
| `36009004`           | Showcase 负向实测：Seller token 请求被拒，HTTP 400 | AUTH_OR_REQUEST_REJECTED     | 否             | 不用 Seller token 调 Creator API；携 request ID 排查 |
| `36009005`           | Profile 负向实测：Seller token 未认证，HTTP 401    | AUTH_SUBJECT_MISMATCH        | 否             | 获取 Creator token；携 request ID 排查               |
| `38007001`           | 平台系统错误                                       | PLATFORM_INTERNAL            | 是             | 指数退避并保留 request ID                            |
| `16011007`           | 标题超过 30 字符                                   | VALIDATION_TITLE_LENGTH      | 否             | 前后端限制并提示修改                                 |
| `16011009`           | 标题含冒犯内容                                     | CONTENT_POLICY               | 否             | 提示修改，不自动绕过                                 |
| `16011069`           | 标题含不支持的标点或 emoji                         | VALIDATION_TITLE_CHARS       | 否             | 标出非法字符                                         |
| `170001002`          | 权限检查失败                                       | SCOPE_OR_ACCOUNT             | 否             | 复核 Scope、主体和账号状态                           |
| `170001003`          | Creator 临时封禁                                   | CREATOR_TEMP_BANNED          | 否             | 禁止发布，显示平台限制                               |
| `170001004`          | Creator 永久封禁                                   | CREATOR_PERM_BANNED          | 否             | 禁止发布，转人工处理                                 |
| `170001005`          | 未签署服务条款                                     | CREATOR_TOS_REQUIRED         | 否             | 引导 Creator 完成签署                                |
| `170001007`          | EU 数据共享协议未签署                              | CREATOR_DATA_AGREEMENT       | 否             | 引导签署对应协议                                     |
| `170001008`          | 年龄验证未完成                                     | CREATOR_AGE_VERIFICATION     | 否             | 引导完成平台验证                                     |
| `170001009`          | 商品类目不支持                                     | PRODUCT_CATEGORY_UNSUPPORTED | 否             | 更换商品                                             |
| `170001010`          | 佣金方案被拒                                       | COLLABORATION_REJECTED       | 否             | 检查合作/佣金状态                                    |
| `170001011`          | 商品不存在                                         | PRODUCT_NOT_FOUND            | 否             | 刷新橱窗/商品映射                                    |
| `170001012`          | 商品不可用                                         | PRODUCT_UNAVAILABLE          | 否             | 移除商品或等待恢复                                   |
| `170001013`          | 橱窗商品达到上限                                   | SHOWCASE_LIMIT               | 否             | 清理橱窗后重试                                       |
| `170001014`          | 内容被识别为 Spam                                  | CONTENT_SPAM                 | 否             | 修改内容并人工复核                                   |
| `170001015`          | 风控拦截                                           | RISK_CONTROL                 | 否             | 不自动重试，转人工处理                               |
| `170001016`          | 内容不属于当前 Creator 或媒体类型不符              | CONTENT_OWNERSHIP            | 否             | 校验 Creator、视频 ID 和类型                         |
| `170001018`          | 收款账户问题                                       | PAY_ACCOUNT_REQUIRED         | 否             | 引导处理平台收款账户                                 |
| `170001020`          | 发布频率限制                                       | RATE_LIMIT_BUSINESS          | 延迟后有限重试 | 使用平台允许时间，不并发轰炸                         |
| `170001024`          | 封面时间戳无效                                     | VALIDATION_COVER_TIME        | 否             | 限制在视频时长范围内                                 |
| `170001025`          | 视频时长超限                                       | VALIDATION_DURATION          | 否             | 上传前校验时长                                       |
| `170001030`          | Creator 被禁止发布                                 | CREATOR_BANNED               | 否             | 禁止发布并转人工                                     |
| `170001031`          | 操作被禁止                                         | FORBIDDEN                    | 否             | 复核账号、市场、Scope                                |
| `170001040`          | video file ID 无效                                 | MEDIA_FILE_INVALID           | 否             | 重新上传并使用新 file ID                             |
| `170001050`          | 平台工作流错误族                                   | PLATFORM_WORKFLOW            | 视子码         | 保存阶段和 request ID，按子码决策                    |
| HTTP `429`           | 请求限流                                           | RATE_LIMIT_HTTP              | 是             | 遵循 `Retry-After`，指数退避                         |
| HTTP `5xx` / timeout | 上游异常                                           | UPSTREAM_TRANSIENT           | 是             | 只对幂等读取或带幂等键操作重试                       |

## 统一错误对象

```json
{
  "category": "SCOPE_MISSING",
  "platformCode": "105005",
  "httpStatus": 400,
  "requestId": "<platform-request-id>",
  "retryable": false,
  "stage": "precheck"
}
```

不得包含 access token、refresh token、授权 code、签名、完整上游请求体或可能含个人数据的原始响应。

## 官方依据

- [Creator Authorization Guide](https://partner.tiktokshop.com/docv2/page/creator-authorization-guide)
- [Post Shoppable Video v202603 error table](https://partner.tiktokshop.com/docv2/page/post-shoppable-video-202603)
- [Get Shoppable Video Status](https://partner.tiktokshop.com/docv2/page/get-shoppable-video-status-202509)
- [Get Showcase Products](https://partner.tiktokshop.com/docv2/page/get-showcase-products)
