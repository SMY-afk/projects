import { Avatar } from 'antd'
import type { AvatarProps } from 'antd/es/avatar/Avatar'
import { useState, type ReactNode } from 'react'

interface Props {
  alt: string
  children?: ReactNode
  size?: AvatarProps['size']
  url?: string | null
}

export function AffiliateAvatar({ alt, children, size, url }: Props) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const image = url && failedUrl !== url ? (
    <img key={url} alt={alt} referrerPolicy="no-referrer" src={url} onError={() => setFailedUrl(url)} />
  ) : undefined
  return (
    <Avatar size={size} src={image}>
      {children}
    </Avatar>
  )
}
