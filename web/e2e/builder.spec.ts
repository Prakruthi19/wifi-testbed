import { test, expect, type Page } from '@playwright/test'

const next = (page: Page, name: string) => page.getByRole('button', { name: `Next: ${name}` })
const add = (page: Page) => page.getByRole('button', { name: '+ Add access point' })

test('builder walks from a home to a checked, shareable plan', async ({ page, context }) => {
  await page.goto('/#/builder')
  await page.getByRole('radio', { name: /Apartment/ }).click()
  await next(page, 'Access points').click()
  await add(page).click()
  await add(page).click()
  await expect(page.locator('g.ap')).toHaveCount(2)

  // Give AP 2 the same 2.4 GHz channel as AP 1 (Auto picks 1 for the first AP): the check flags it.
  await page.locator('select').first().selectOption('1')
  await next(page, 'Check').click()
  await expect(page.getByText(/AP 1 and AP 2 share channel 1 on 2.4 GHz/)).toBeVisible()
  await expect(page.getByRole('table')).toContainText('Living + kitchen')

  await next(page, 'Review').click()
  const link = await page.locator('#share').inputValue()
  expect(link).toContain('#/builder?plan=')

  // The link opens the same plan on another page, on the Check step.
  const other = await context.newPage()
  await other.goto(link)
  await expect(other.locator('g.ap')).toHaveCount(2)
  await expect(other.getByRole('button', { name: 'Check' })).toHaveAttribute('aria-current', 'step')
  await expect(other.getByText(/share channel 1/)).toBeVisible()
})

test('builder will not move on while a name is missing, and says why', async ({ page }) => {
  await page.goto('/#/builder')
  await next(page, 'Access points').click()
  await next(page, 'Check').click()
  await expect(page.getByText('Add at least one access point.')).toBeVisible()
  await add(page).click()
  const name = page.getByLabel('Name')
  await name.fill('')
  await name.blur()
  await next(page, 'Check').click()
  await expect(page.getByText('Give this access point a name.')).toBeVisible()
  await expect(name).toHaveAttribute('aria-invalid', 'true')
  await expect(name).toBeFocused()
  await name.fill('Hallway')
  await name.blur()
  await next(page, 'Check').click()
  await expect(page.getByRole('heading', { name: 'Check the plan' })).toBeVisible()
})

test('a 2.4 GHz-only model turns off the 5 GHz choices', async ({ page }) => {
  await page.goto('/#/builder')
  await next(page, 'Access points').click()
  await add(page).click()
  await page.getByText('Compact', { exact: true }).click()
  await expect(page.getByRole('radiogroup', { name: 'Band', exact: true }).getByRole('radio', { name: '5 GHz', exact: true })).toBeDisabled()
  await expect(page.getByRole('radiogroup', { name: 'Band', exact: true }).getByRole('radio', { name: '2.4 GHz', exact: true })).toHaveAttribute('aria-checked', 'true')
  await expect(page.getByText('5 GHz channel')).toHaveCount(0)
})

test('undo and redo, and arrow keys move an access point', async ({ page, isMobile }) => {
  await page.goto('/#/builder')
  await next(page, 'Access points').click()
  await add(page).click()
  const ap = page.locator('g.ap').first()
  if (!isMobile) {
    const before = await ap.getAttribute('transform')
    await ap.focus()
    await page.keyboard.press('ArrowRight')
    await expect(ap).not.toHaveAttribute('transform', before!)
    await page.getByRole('button', { name: 'Undo' }).click()
    await expect(ap).toHaveAttribute('transform', before!)
  }
  await page.getByRole('button', { name: 'Undo' }).click()
  await expect(page.locator('g.ap')).toHaveCount(0)
  await page.getByRole('button', { name: 'Redo' }).click()
  await expect(page.locator('g.ap')).toHaveCount(1)
})

test('a plan downloads as a readable file and uploads back, and a bad file is refused', async ({ page }) => {
  await page.goto('/#/builder')
  await page.getByRole('radio', { name: /Small office/ }).click()
  await next(page, 'Access points').click()
  await add(page).click()
  await add(page).click()

  const [file] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download' }).click()])
  expect(file.suggestedFilename()).toBe('wifi-plan-office.json')
  const text = await (await import('node:fs/promises')).readFile((await file.path())!, 'utf8')
  const saved = JSON.parse(text)
  expect(saved).toMatchObject({ format: 'wifi-plan', version: 1, home: 'office' })
  expect(saved.accessPoints.map((a: { name: string }) => a.name)).toEqual(['AP 1', 'AP 2'])

  // A fresh page: upload the file and get the same plan back on the Check step.
  await page.goto('/#/sites')
  await page.reload()
  await page.goto('/#/builder')
  await expect(page.locator('g.ap')).toHaveCount(0)
  await page.getByLabel('Upload a plan file').setInputFiles({ name: 'mine.json', mimeType: 'application/json', buffer: Buffer.from(text) })
  await expect(page.getByRole('status')).toContainText('Loaded mine.json')
  await expect(page.locator('g.ap')).toHaveCount(2)
  await expect(page.getByRole('button', { name: 'Check' })).toHaveAttribute('aria-current', 'step')

  await page.getByLabel('Upload a plan file').setInputFiles({ name: 'notes.json', mimeType: 'application/json', buffer: Buffer.from('{"hello": 1}') })
  await expect(page.getByRole('status')).toContainText('not a Wi-Fi plan')
  await expect(page.locator('g.ap')).toHaveCount(2) // the loaded plan is untouched
})

test('the demo says saving by name needs the lab API', async ({ page }) => {
  await page.goto('/#/builder')
  await expect(page.getByRole('heading', { name: 'Saved plans' })).toBeVisible()
  await expect(page.getByText(/Saving by name needs the lab API/)).toBeVisible()
  await page.getByRole('button', { name: 'Next: Access points' }).click()
  await page.getByRole('button', { name: '+ Add access point' }).click()
  await page.getByRole('button', { name: 'Next: Check' }).click()
  await page.getByRole('button', { name: 'Next: Review' }).click()
  await expect(page.getByLabel('Save as')).toHaveCount(0)
})

test('the tab title stays the app name on every page, with the logo as its icon', async ({ page }) => {
  for (const path of ['/#/sites', '/#/runs', '/#/builder', '/#/login']) {
    await page.goto(path)
    await expect(page).toHaveTitle('Wi-Fi Test Lab')
  }
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute('href', /favicon\.svg$/)
  expect((await page.request.get('favicon.svg')).ok()).toBe(true)
})

test('the demo login page explains that logging in needs the lab', async ({ page }) => {
  await page.goto('/#/login')
  await expect(page.getByRole('heading', { name: 'Log in' })).toBeVisible()
  await expect(page.getByText(/Logging in needs the lab API/)).toBeVisible()
  await expect(page.getByLabel('Password')).toHaveCount(0)
})
