import type { ThemeConfig } from 'antd'

export const appTheme: ThemeConfig = {
  token: {
    colorPrimary: '#167169',
    colorInfo: '#167169',
    colorBgLayout: '#f3f5fb',
    colorBgContainer: '#ffffff',
    colorText: '#173636',
    colorTextSecondary: '#637772',
    borderRadius: 6,
    fontSize: 14,
    fontFamily: 'Inter, "PingFang SC", "Microsoft YaHei", sans-serif',
  },
  components: {
    Layout: {
      bodyBg: '#f3f5fb',
      headerBg: '#ffffff',
      siderBg: '#073b3a',
      triggerBg: '#073b3a',
    },
    Menu: {
      darkItemBg: '#073b3a',
      darkItemHoverBg: '#195b57',
      darkItemSelectedBg: '#167169',
      darkSubMenuItemBg: '#073b3a',
    },
  },
}
