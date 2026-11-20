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
  await page.getByRole('button', { name: 'Table' }).click()
  await page.getByRole('link').filter({ hasText: /2026/ }).last().click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Test run of')
  const first = page.locator('article').first()
  await expect(first.locator('.verdict')).toContainText(/failed|crashed/)
  await expect(page.getByText('stopped here').first()).toBeAttached()
})

test('filter shows only runs with failures', async ({ page }) => {
  await page.goto('/#/runs')
  await page.getByRole('button', { name: 'Table' }).click()
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
  for (const path of ['/', '/#/runs', '/#/coverage', '/#/start']) {
    await page.goto(path)
    await page.waitForLoadState('networkidle')
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow, `page ${path} scrolls sideways`).toBeLessThanOrEqual(0)
  }
})

test('channel map flags no overlap for the home mesh on 1, 6 and 11', async ({ page }) => {
  await page.goto('/')
  const home = page.locator('section', { hasText: 'Home mesh: channel map' })
  await expect(home.getByText('No overlapping channels')).toBeVisible()
  await home.locator('g.ap').first().focus()
  await expect(home.getByText(/channel \d+ \(\d+ MHz centre/)).toBeVisible()
})

test('results grid: a square opens its run', async ({ page }) => {
  await page.goto('/#/runs')
  const cell = page.getByRole('button', { name: /Device blocked by the router, run 1: failed/ })
  await cell.focus()
  await expect(page.locator('.tip')).toContainText('failed')
  await cell.click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Test run of')
})

test('coverage planner: on 5 GHz the router alone covers less than with both mesh points', async ({ page }) => {
  await page.goto('/#/coverage')
  await expect(page.getByText('This is a model, not a measurement')).toBeVisible()
  await page.getByRole('button', { name: '5 GHz' }).click()
  const stat = page.locator('.stat b')
  const withMesh = parseInt((await stat.textContent())!)
  await page.getByRole('checkbox', { name: /mesh-living/ }).uncheck()
  await page.getByRole('checkbox', { name: /mesh-bedroom/ }).uncheck()
  await expect.poll(async () => parseInt((await stat.textContent())!)).toBeLessThan(withMesh)
})

test('coverage planner: keyboard can move the router', async ({ page }) => {
  await page.goto('/#/coverage')
  const router = page.locator('g.ap').first()
  const before = await router.getAttribute('transform')
  await router.focus()
  await page.keyboard.press('ArrowRight')
  await expect(router).not.toHaveAttribute('transform', before!)
})

test('coverage planner: walking the phone on 5 GHz roams to a mesh point', async ({ page }) => {
  await page.goto('/#/coverage')
  await page.getByRole('button', { name: '5 GHz' }).click()
  await page.getByRole('button', { name: '10×' }).click()
  await page.getByRole('button', { name: /Walk the phone/ }).click()
  const log = page.getByRole('list', { name: /What happened on the walk/ })
  await expect(log).toContainText('joined router')
  await expect(log).toContainText(/moved from router \(-\d+ dBm\) to mesh-/, { timeout: 15_000 })
  await expect(log).toContainText('walk finished', { timeout: 15_000 })
  await expect(page.getByRole('button', { name: /Walk again/ })).toBeVisible()
})

test('run detail explains each test in plain words', async ({ page }) => {
  await page.goto('/#/runs/20260928T030500Z')
  const card = page.locator('article', { hasText: 'Wrong Wi-Fi password (WPA2)' })
  await expect(card.getByText('What it does:')).toBeVisible()
  await expect(card.locator('.verdict')).toContainText('failed on purpose')
  await expect(card.getByText('That is exactly where this broken setup should stop.')).toBeVisible()
  const roam = page.locator('article', { hasText: 'Fast roaming (802.11r)' })
  await expect(roam.getByText('Time to switch access point')).toBeVisible()
  await expect(roam.getByText('56.7 ms')).toBeVisible()
})
