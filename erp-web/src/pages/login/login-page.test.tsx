import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import LoginPage from './login-page'

const mocks = vi.hoisted(() => ({
  getCaptcha: vi.fn(),
  login: vi.fn(),
}))

vi.mock('@/auth/use-auth', () => ({
  useAuth: () => ({ isAuthenticated: false, login: mocks.login }),
}))

vi.mock('@/services/auth', () => ({
  authApi: { getCaptcha: mocks.getCaptcha },
  CAPTCHA_CODE_LENGTH: 5,
}))

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        addEventListener: vi.fn(),
        addListener: vi.fn(),
        dispatchEvent: vi.fn(),
        matches: false,
        media: query,
        onchange: null,
        removeEventListener: vi.fn(),
        removeListener: vi.fn(),
      })),
    })
    mocks.getCaptcha.mockResolvedValue({
      captchaId: 'captcha-id',
      imageDataUrl: 'data:image/svg+xml;base64,PHN2Zy8+',
    })
  })

  it('shows only username and password without requesting a captcha', async () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    expect(screen.queryByRole('img', { name: '验证码图片' })).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText('请输入图中验证码')).not.toBeInTheDocument()
    await userEvent.setup().type(screen.getByPlaceholderText('请输入用户名'), 'component-user')
    expect(mocks.getCaptcha).not.toHaveBeenCalled()
  })

  it('shows login failure without reloading a captcha', async () => {
    mocks.login.mockRejectedValueOnce(new Error('用户名或密码错误'))
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    await user.type(screen.getByPlaceholderText('请输入用户名'), 'component-user')
    await user.type(screen.getByPlaceholderText('请输入密码'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: /登\s*录/ }))
    expect(await screen.findByText('用户名或密码错误')).toBeInTheDocument()
    expect(mocks.getCaptcha).not.toHaveBeenCalled()
  })

  it('submits username and password without captcha fields', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    await user.type(screen.getByPlaceholderText('请输入用户名'), 'component-user')
    await user.type(screen.getByPlaceholderText('请输入密码'), 'component-password')
    await user.click(screen.getByRole('button', { name: /登\s*录/ }))

    expect(mocks.login).toHaveBeenCalledWith({
      username: 'component-user',
      password: 'component-password',
    })
  })

  it('explains when the previous session expired', async () => {
    render(
      <MemoryRouter initialEntries={[{ pathname: '/login', state: { sessionExpired: true } }]}>
        <LoginPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('登录已失效，请重新登录。')).toBeInTheDocument()
  })
})
