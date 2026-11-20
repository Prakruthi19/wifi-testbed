import { test, expect } from '@playwright/test'

test('lab overview lists the access points from the inventory', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Lab overview' })).toBeVisible()
  await expect(page.getByText('lab-wpa2', { exact: true })).toBeVisible()
  await expect(page.getByText('WPA3-Personal (SAE)')).toBeVisible()
})

test('placeholder data is labelled as not real', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('note')).toBeVisible()
})

test('runs list opens a run with failures first and a join timeline', async ({ page }) => {
  await page.goto('/#/runs')
  await page.getByRole('link').filter({ hasText: /2026/ }).last().click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Run of')
  const first = page.locator('article').first()
  await expect(first.locator('.badge')).toHaveText(/failed|error/)
  await expect(page.getByText('failed here').first()).toBeAttached()
})

test('filter shows only runs with failures', async ({ page }) => {
  await page.goto('/#/runs')
  const rows = page.locator('tbody tr')
  const before = await rows.count()
  await page.getByLabel('Only runs with failures').check()
  await expect(rows).toHaveCount(before - 1)
})

test('demo cannot start runs', async ({ page }) => {
  await page.goto('/#/start')
  await expect(page.getByRole('button', { name: 'Start run' })).toBeDisabled()
})

test('no sideways scrolling on any page', async ({ page }) => {
  for (const path of ['/', '/#/runs', '/#/start']) {
    await page.goto(path)
    await page.waitForLoadState('networkidle')
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow, `page ${path} scrolls sideways`).toBeLessThanOrEqual(0)
  }
})
