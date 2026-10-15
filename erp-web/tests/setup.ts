import '@testing-library/jest-dom/vitest'

const browserGetComputedStyle = window.getComputedStyle.bind(window)

window.getComputedStyle = (element, pseudoElement) =>
  browserGetComputedStyle(element, pseudoElement?.startsWith('::') ? undefined : pseudoElement)
