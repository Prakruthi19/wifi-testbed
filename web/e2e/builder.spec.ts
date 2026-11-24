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
  await expect(page.getByRole('radio', { name: '5 GHz', exact: true })).toBeDisabled()
  await expect(page.getByRole('radio', { name: '2.4 GHz', exact: true })).toHaveAttribute('aria-checked', 'true')
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
