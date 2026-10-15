import { ReloadOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import './image-captcha.css'

interface ImageCaptchaProps {
  imageDataUrl?: string
  loading?: boolean
  onRefresh: () => void
}

export default function ImageCaptcha({ imageDataUrl, loading = false, onRefresh }: ImageCaptchaProps) {
  return (
    <div className="image-captcha">
      {imageDataUrl ? (
        <img alt="验证码图片" className="image-captcha__image" src={imageDataUrl} />
      ) : (
        <div className="image-captcha__placeholder" />
      )}
      <Button aria-label="刷新验证码" icon={<ReloadOutlined />} loading={loading} onClick={onRefresh} type="text" />
    </div>
  )
}
