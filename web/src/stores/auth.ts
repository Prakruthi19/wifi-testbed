import { defineStore } from 'pinia'
import { ref } from 'vue'
import { DEMO, api, type User } from '../api'

// Who is logged in. The session itself is an HttpOnly cookie the browser holds; this store only
// remembers the answer to "who am I?" so the page can show the right buttons.
export const useAuth = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const checked = ref(DEMO) // the demo has no API, so there is nothing to check

  async function load() {
    if (DEMO || checked.value) return
    try { user.value = await api.auth.me() } catch { user.value = null }
    checked.value = true
  }
  async function login(email: string, password: string) {
    user.value = await api.auth.login(email, password)
    checked.value = true
  }
  async function logout() {
    try { await api.auth.logout() } finally { user.value = null }
  }
  // Called when the API answers 401: the session ended (idle, expired, or logged out elsewhere).
  const expired = () => { user.value = null }

  return { user, checked, load, login, logout, expired }
})
