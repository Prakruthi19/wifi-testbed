import { test, expect, type Page } from '@playwright/test'

// One row per home, in whichever view is showing (a table on desktop, cards on phones).
const homes = (page: Page) => page.locator('table[aria-label="Homes"] tbody tr, ul[aria-label="Homes"] > li')

test('lab overview lists the access points from the inventory', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Lab overview' })).toBeVisible()
  await expect(page.getByText('lab-wpa2', { exact: true })).toBeVisible()
  await expect(page.getByText('WPA3-Personal (SAE)')).toBeVisible()
})

test('placeholder data is labelled as not real', async ({ page }) => {
  await page.goto('/')
  const chip = page.getByText('Sample data', { exact: true })
  await expect(chip).toBeVisible()
  await expect(chip).toHaveAttribute('title', /not results from a real lab run/)
})

test('runs list opens a run with failures first and a join timeline', async ({ page }) => {
  await page.goto('/#/runs')
  const rows = page.getByRole('table', { name: 'Runs' }).locator('tbody tr')
  await expect(rows.last()).toContainText('2 failed: Device blocked by the router, Address server switched off')
  await rows.last().getByRole('link').click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Test run of')
  // Failed tests start open, at the top.
  const first = page.locator('article').first()
  await expect(first.locator('.verdict')).toContainText(/failed|crashed/)
  await expect(page.getByText('stopped here').first()).toBeAttached()
})

test('filter shows only runs with failures', async ({ page }) => {
  await page.goto('/#/runs')
  const rows = page.getByRole('table', { name: 'Runs' }).locator('tbody tr')
  const before = await rows.count()
  await page.getByLabel('Only runs with failures').check()
  await expect(rows).toHaveCount(before - 1)
})

test('demo cannot start runs', async ({ page }) => {
  await page.goto('/#/start')
  await expect(page.getByRole('button', { name: 'Start run' })).toBeDisabled()
})

test('no sideways scrolling on any page', async ({ page }) => {
  for (const path of ['/', '/#/runs', '/#/sites', '/#/sites/oak-7', '/#/coverage', '/#/start']) {
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
  await page.getByRole('tab', { name: /Flaky tests/ }).click()
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

test('sites portal: lists every home, worst first, and says which are simulated', async ({ page }) => {
  await page.goto('/#/sites')
  await page.getByText('About this data').click()
  await expect(page.getByText(/Only "Lab home" comes from the test bed/)).toBeVisible()
  const cards = homes(page)
  await expect(cards).toHaveCount(8)
  await expect(cards.first()).toContainText('Offline')
  await expect(cards.filter({ hasText: 'Lab home' })).toContainText('Healthy')
  await page.getByRole('button', { name: 'Offline', exact: true }).click()
  await expect(cards).toHaveCount(1)
  await expect(cards.first()).toContainText('31 Riverside Drive')
})

test('sites portal: switching a mesh point off on a home updates the overview', async ({ page }) => {
  await page.goto('/#/sites')
  await page.getByRole('link', { name: /12 Maple Street/ }).first().click()
  await expect(page.getByRole('heading', { name: '12 Maple Street' })).toBeVisible()
  await page.getByRole('checkbox', { name: /mesh-1/ }).uncheck()
  await expect(page.locator('.issues')).toContainText('mesh-1 is offline')
  await page.getByRole('link', { name: /All sites/ }).click()
  const maple = homes(page).filter({ hasText: '12 Maple Street' })
  await expect(maple).toContainText('Degraded')
  await expect(page.getByRole('list', { name: /Recent changes/ })).toContainText('mesh-1 is offline')
})

test('floor plan lines agree with the Health card whatever floor band is shown', async ({ page }) => {
  await page.goto('/#/sites/harbor-4b')
  await expect(page.locator('.issues')).toContainText('laptop has a weak signal')
  for (const band of ['2.4 GHz', '5 GHz']) {
    await page.getByRole('button', { name: band, exact: true }).click()
    await expect(page.locator('g.device[aria-label^="laptop:"]')).toHaveAttribute('aria-label', /laptop: -\d+ dBm on 5 GHz via router/)
    await expect(page.locator('path.link.weak')).toHaveCount(3)
  }
})

test('dashboard: sidebar collapses, theme switches, and the homes view toggles', async ({ page, isMobile }) => {
  await page.goto('/#/sites')
  await page.getByRole('button', { name: 'Table', exact: true }).click()
  await expect(page.getByRole('table', { name: 'Homes' })).toBeVisible()
  await page.getByRole('button', { name: 'Cards', exact: true }).click()
  await expect(page.getByRole('list', { name: 'Homes' })).toBeVisible()
  await expect(homes(page)).toHaveCount(8)
  await page.getByRole('button', { name: 'Theme: match system' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await page.getByRole('button', { name: 'Theme: light' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.getByRole('navigation').getByRole('link', { name: 'Test runs' }).click()
  await expect(page).toHaveURL(/#\/runs/)
  if (!isMobile) {
    await page.getByRole('button', { name: 'Collapse menu' }).click()
    await expect(page.getByRole('button', { name: 'Expand menu' })).toBeVisible()
    await expect(page.getByRole('navigation').getByText('Test runs')).toBeHidden()
  }
})

test('run detail explains each test in plain words', async ({ page }) => {
  await page.goto('/#/runs/20260928T030500Z')
  await expect(page.getByText('All 7 passed').first()).toBeVisible()
  // Passed tests start closed; open two rows.
  await page.getByRole('button', { name: 'Wrong Wi-Fi password (WPA2)' }).click()
  await page.getByRole('button', { name: 'Fast roaming (802.11r)' }).click()
  const card = page.getByRole('article', { name: 'Wrong Wi-Fi password (WPA2)' })
  await expect(card.getByText('What it does:')).toBeVisible()
  await expect(card.locator('.verdict')).toContainText('failed on purpose')
  await expect(card.getByText('That is exactly where this broken setup should stop.')).toBeVisible()
  const roam = page.getByRole('article', { name: 'Fast roaming (802.11r)' })
  await expect(roam.getByText('Time to switch access point')).toBeVisible()
  await expect(roam.getByText('56.7 ms')).toBeVisible()
})
