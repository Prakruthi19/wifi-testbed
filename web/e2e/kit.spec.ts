import { test, expect } from '@playwright/test'

test('UI kit shows live token values, a keyboard-friendly segmented control and field errors', async ({ page, isMobile }) => {
  await page.goto('/#/kit')
  await expect(page.getByRole('heading', { name: 'UI kit' })).toBeVisible()
  // Swatches show the token's current value (light theme by default).
  await expect(page.getByRole('button', { name: 'Copy --accent', exact: true })).toContainText('#4f46e5')

  const band = page.getByRole('radiogroup', { name: 'Band' })
  await expect(band.getByRole('radio', { name: '5 GHz' })).toHaveAttribute('aria-checked', 'true')
  await expect(band.getByRole('radio', { name: '6 GHz' })).toBeDisabled()
  if (!isMobile) {
    await band.getByRole('radio', { name: '5 GHz' }).focus()
    await page.keyboard.press('ArrowRight') // skips the disabled 6 GHz and wraps to 2.4 GHz
    await expect(band.getByRole('radio', { name: '2.4 GHz' })).toHaveAttribute('aria-checked', 'true')
    await expect(band.getByRole('radio', { name: '2.4 GHz' })).toBeFocused()
  }

  const ssid = page.getByLabel('Network name (SSID)')
  await ssid.focus()
  await ssid.blur()
  await expect(page.getByText('Enter a network name.')).toBeVisible()
  await expect(ssid).toHaveAttribute('aria-invalid', 'true')
})

test.describe('in dark mode', () => {
  test.use({ colorScheme: 'dark' })
  test('UI kit swatches follow the dark theme', async ({ page }) => {
    await page.goto('/#/kit')
    await expect(page.getByRole('button', { name: 'Copy --accent', exact: true })).toContainText('#818cf8')
  })
})
