import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface DeveloperState {
  isDeveloperMode: boolean
  toggleDeveloperMode: () => void
  setDeveloperMode: (enabled: boolean) => void
}

export const useDeveloperStore = create<DeveloperState>()(
  persist(
    (set) => ({
      isDeveloperMode: false,
      toggleDeveloperMode: () => set((state) => ({ isDeveloperMode: !state.isDeveloperMode })),
      setDeveloperMode: (enabled) => set({ isDeveloperMode: enabled }),
    }),
    {
      name: 'developer-storage',
    }
  )
)
