import { test, expect } from '@playwright/test'

// The demo has no lab, so the Capture page shows one made-up example capture and cannot start one.
test('demo capture page shows the sample analysis, labelled as made up', async ({ page }) => {
  await page.goto('/#/capture')
  await expect(page.getByRole('heading', { name: 'Packet capture' })).toBeVisible()
  await expect(page.getByText('Made-up example capture (synthetic frames')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Start capture' })).toBeDisabled()
  const devices = page.locator('table[aria-label="Devices"] tbody tr')
  await expect(devices).toHaveCount(2)
  await expect(devices.nth(0)).toContainText('Joined and got an address')
  await expect(devices.nth(1)).toContainText('Failed at 4-way handshake')
  await expect(page.getByText('Reason 15: 4-way handshake timeout')).toBeVisible()
  await expect(page.getByText('Incomplete')).toBeVisible()
})
