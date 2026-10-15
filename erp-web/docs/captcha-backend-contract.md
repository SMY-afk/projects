# Production captcha contract

Set `VITE_USE_MOCK=false` in production. The browser does not generate or validate captcha answers.

## `GET /auth/captcha`

Return a no-store response containing an opaque, unpredictable challenge id and the rendered image:

```json
{ "captchaId": "opaque-one-time-id", "imageDataUrl": "data:image/png;base64,..." }
```

The image may instead be a protected URL, but it must correspond to the same challenge id.

## `POST /auth/login`

Require all four fields and validate the captcha on the server:

```json
{ "username": "user", "password": "password", "captchaId": "opaque-one-time-id", "captchaCode": "ABCD" }
```

The challenge must be valid for **2–5 minutes** (this frontend's Mock implementation uses 2 minutes), store only a hash of the answer, and be invalidated atomically after every login attempt (success or failure). A successful login therefore always consumes the captcha. A wrong captcha also consumes it; the frontend then requests a new challenge. Captcha comparison is case-insensitive: normalize both the stored answer and `captchaCode` to uppercase (the frontend sends uppercase). Clicking “换一张” must issue a new `GET /auth/captcha` request and discard the previous challenge.

Bind each challenge to a session or similarly constrained context, rate-limit generation and login by IP/account, and return a generic 400/401 error for invalid, expired, or reused challenges. Never trust a client-provided “verified” flag. Return `Cache-Control: no-store` for captcha responses.
