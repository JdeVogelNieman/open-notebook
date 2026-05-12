import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface NotebookColumnsState {
  sourcesCollapsed: boolean
  notesCollapsed: boolean
  previewCollapsed: boolean
  toggleSources: () => void
  toggleNotes: () => void
  togglePreview: () => void
  setSources: (collapsed: boolean) => void
  setNotes: (collapsed: boolean) => void
  setPreview: (collapsed: boolean) => void
}

export const useNotebookColumnsStore = create<NotebookColumnsState>()(
  persist(
    (set) => ({
      sourcesCollapsed: false,
      notesCollapsed: false,
      previewCollapsed: false,
      toggleSources: () => set((state) => ({ sourcesCollapsed: !state.sourcesCollapsed })),
      toggleNotes: () => set((state) => ({ notesCollapsed: !state.notesCollapsed })),
      togglePreview: () => set((state) => ({ previewCollapsed: !state.previewCollapsed })),
      setSources: (collapsed) => set({ sourcesCollapsed: collapsed }),
      setNotes: (collapsed) => set({ notesCollapsed: collapsed }),
      setPreview: (collapsed) => set({ previewCollapsed: collapsed }),
    }),
    {
      name: 'notebook-columns-storage',
    }
  )
)
