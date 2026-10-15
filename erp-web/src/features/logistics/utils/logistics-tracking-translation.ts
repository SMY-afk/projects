const descriptions: Record<string, string> = {
  'order placed': '已下单。',
  'package details received by the carrier': '承运商已收到包裹详细信息。',
  'order packed and ready for pickup': '订单已打包，正在等待承运商揽收。',
  "order packed and ready for dropoff at carrier's facility": '订单已打包，正在等待在承运商的仓储场所卸货。',
  'package is being prepared at warehouse': '包裹正在仓库备货。',
  'package is ready and will be handed over to the carrier soon': '包裹已准备好，即将交给承运商。',
  'arrived at the sorting center': '已到达分拣中心。',
  'in transit': '运输中。',
  'in transit to the next facility': '正在运往下一个仓储场所。',
  'out for delivery': '正在派送。',
  'package has been delivered': '包裹已送达。',
  delivered: '已送达。',
}

const deliveryLocations: Record<string, string> = {
  'front door/porch': '前门/门廊',
  'front desk/reception/mail room': '前台/接待处/收发室',
  'in/at mailbox': '信箱内/信箱处',
  'parcel locker': '包裹柜',
  'left with individual': '已交给收件人',
  'garage or other location at address': '地址处的车库或其他位置',
  'individual picked up at postal facility': '收件人已在邮政网点领取',
}

// Translate known official templates only. Captured place names retain their original spelling.
export function translateTrackingDescription(description?: string | null): string {
  if (!description) return ''
  const source = description.trim()
  const key = source.toLowerCase().replace(/’/g, "'").replace(/[.!]+$/, '')
  if (Object.hasOwn(descriptions, key)) return descriptions[key]

  const facility = source.match(/^(Arrived at|Departed(?: from)?) (?:the )?(.+?) (carrier['’]s|destination|shipping partner['’]s) facility[.!]?$/i)
  if (facility) {
    const [, action, place, owner] = facility
    const verb = action.toLowerCase().startsWith('arrived') ? '已到达' : '已离开'
    const kind = owner.toLowerCase().replace(/’/g, "'")
    if (kind === 'destination') return `${verb}${place}目的地仓储场所。`
    return `${verb}${kind === "carrier's" ? '承运商' : '物流合作伙伴'}的${place}仓储场所。`
  }

  const pickup = source.match(/^Package picked up and currently at (.+?)[.!]?$/i)
  if (pickup) return `包裹已被揽收，目前位于${pickup[1]}。`

  const delivery = key.match(/^delivered,\s*(.+)$/)
  if (delivery && Object.hasOwn(deliveryLocations, delivery[1])) return `已送达，${deliveryLocations[delivery[1]]}。`
  return description
}
