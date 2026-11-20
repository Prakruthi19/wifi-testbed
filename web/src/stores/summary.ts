import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type Summary } from '../api'

// The header and several screens all need the summary, so it is loaded once and shared.
export const useSummary = defineStore('summary', () => {
  const data = ref<Summary | null>(null)
  const error = ref<string | null>(null)

  async function load() {
    try {
      data.value = await api.summary()
      error.value = null
    } catch (e) {
      error.value = (e as Error).message
    }
  }

  return { data, error, load }
})
