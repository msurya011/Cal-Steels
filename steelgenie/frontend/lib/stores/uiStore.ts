import { create } from 'zustand'

export interface Toast {
  type: 'blue' | 'green' | 'red'
  message: string
}

interface UiState {
  toast: Toast | null
  showToast: (type: 'blue' | 'green' | 'red', message: string) => void
  hideToast: () => void
}

export const useUiStore = create<UiState>((set) => ({
  toast: null,
  showToast: (type, message) => {
    set({ toast: { type, message } })
    // Auto-dismiss in 4 seconds
    setTimeout(() => {
      set((state) => {
        if (state.toast?.message === message) {
          return { toast: null }
        }
        return {}
      })
    }, 4000)
  },
  hideToast: () => set({ toast: null }),
}))
