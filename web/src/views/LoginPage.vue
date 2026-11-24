<script setup lang="ts">
// Email and password log in. The server answers with an HttpOnly cookie, so nothing secret is kept here.
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { DEMO } from '../api'
import { BaseButton } from '../components/ui'
import { useAuth } from '../stores/auth'

const auth = useAuth()
const route = useRoute()
const router = useRouter()
const email = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

// Only same-app paths, so a crafted link (?next=https://evil.example) cannot send people elsewhere.
const next = () => { const n = route.query.next; return typeof n === 'string' && n.startsWith('/') && !n.startsWith('//') ? n : '/builder' }

async function submit() {
  error.value = ''
  if (!email.value.trim() || !password.value) { error.value = 'Enter your email and password.'; return }
  busy.value = true
  try {
    await auth.login(email.value, password.value)
    password.value = ''
    router.replace(next())
  } catch (e) {
    error.value = (e as Error).message
    password.value = ''
  } finally { busy.value = false }
}
</script>

<template>
  <div class="wrap">
    <form class="card login" novalidate @submit.prevent="submit">
      <h1>Log in</h1>
      <p v-if="DEMO" class="muted">Logging in needs the lab API, so it works when you run the app in the VM. This demo is read-only.</p>
      <template v-else-if="auth.user">
        <p>You are logged in as <b>{{ auth.user.email }}</b>.</p>
        <BaseButton variant="secondary" @click="auth.logout()">Log out</BaseButton>
      </template>
      <template v-else>
        <p class="muted">Log in to save network plans and open the ones your team saved.</p>
        <label class="field">
          <span>Email</span>
          <input v-model="email" type="email" autocomplete="username" required :aria-invalid="!!error" aria-describedby="login-err" />
        </label>
        <label class="field">
          <span>Password</span>
          <input v-model="password" type="password" autocomplete="current-password" required :aria-invalid="!!error" aria-describedby="login-err" />
        </label>
        <p id="login-err" class="error" role="alert">{{ error }}</p>
        <BaseButton type="submit" :disabled="busy">{{ busy ? 'Logging in…' : 'Log in' }}</BaseButton>
      </template>
    </form>
  </div>
</template>

<style scoped>
.wrap { display: grid; place-items: start center; padding-top: 6vh; }
.login { width: min(400px, 100%); display: grid; gap: 14px; padding: 28px; }
h1 { margin: 0; font-size: 22px; }
p { margin: 0; }
.field { display: grid; gap: 6px; font-size: 13px; font-weight: 600; }
.field input { font: inherit; font-weight: 400; font-size: 15px; padding: 10px 12px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--card); color: var(--ink); }
.field input[aria-invalid='true'] { border-color: var(--fail); }
.error { color: var(--fail); font-size: 13px; min-height: 1em; }
.error:empty { display: none; }
</style>
