'use client'

import { useState, useEffect, useRef } from 'react'
import { useParams } from 'next/navigation'
import { AppShell } from '@/components/layout/AppShell'
import { NotebookHeader } from '../components/NotebookHeader'
import { SourcesColumn } from '../components/SourcesColumn'
import { ChatColumn } from '../components/ChatColumn'
import { PreviewColumn } from '../components/PreviewColumn'
import { useNotebook } from '@/lib/hooks/use-notebooks'
import { useNotebookSources } from '@/lib/hooks/use-sources'
import { useNotes } from '@/lib/hooks/use-notes'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useNotebookColumnsStore } from '@/lib/stores/notebook-columns-store'
import { useIsDesktop } from '@/lib/hooks/use-media-query'
import { useTranslation } from '@/lib/hooks/use-translation'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FileText, MessageSquare, FileOutput } from 'lucide-react'
import { SourceListResponse } from '@/lib/types/api'
import { Panel, Group as PanelGroup, Separator as PanelResizeHandle, usePanelRef } from 'react-resizable-panels'

export type ContextMode = 'off' | 'insights' | 'full'

export interface ContextSelections {
  sources: Record<string, ContextMode>
  notes: Record<string, ContextMode>
}

export default function NotebookPage() {
  const { t } = useTranslation()
  const params = useParams()

  // Ensure the notebook ID is properly decoded from URL
  const notebookId = params?.id ? decodeURIComponent(params.id as string) : ''

  const { data: notebook, isLoading: notebookLoading } = useNotebook(notebookId)
  const {
    sources,
    isLoading: sourcesLoading,
    refetch: refetchSources,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useNotebookSources(notebookId)
  const { data: notes } = useNotes(notebookId)

  // Get collapse states for dynamic layout
  const { sourcesCollapsed, previewCollapsed, setSources, setPreview } = useNotebookColumnsStore()

  // Detect desktop to avoid double-mounting ChatColumn
  const isDesktop = useIsDesktop()

  // Mobile tab state (Sources, Chat, or Preview)
  const [mobileActiveTab, setMobileActiveTab] = useState<'sources' | 'chat' | 'preview'>('chat')

  // Preview source state – set when user drags or clicks "Send to Preview"
  const [previewSource, setPreviewSource] = useState<SourceListResponse | null>(null)

  // Ref to imperatively collapse/expand the preview panel
  const previewPanelRef = usePanelRef()
  const sourcePanelRef = usePanelRef()
  // Guard flag to prevent sync loops when we programmatically collapse/expand
  const skipPanelSync = useRef(false)

  // Sync Zustand collapse state → panel (on external toggle button click)
  useEffect(() => {
    skipPanelSync.current = true
    if (previewCollapsed) previewPanelRef.current?.collapse()
    else previewPanelRef.current?.expand()
    const t = setTimeout(() => { skipPanelSync.current = false }, 150)
    return () => clearTimeout(t)
  }, [previewCollapsed, previewPanelRef])

  useEffect(() => {
    skipPanelSync.current = true
    if (sourcesCollapsed) sourcePanelRef.current?.collapse()
    else sourcePanelRef.current?.expand()
    const t = setTimeout(() => { skipPanelSync.current = false }, 150)
    return () => clearTimeout(t)
  }, [sourcesCollapsed, sourcePanelRef])

  // Context selection state
  const [contextSelections, setContextSelections] = useState<ContextSelections>({
    sources: {},
    notes: {}
  })

  // Initialize and update selections when sources load or change
  useEffect(() => {
    if (sources && sources.length > 0) {
      setContextSelections(prev => {
        const newSourceSelections = { ...prev.sources }
        sources.forEach(source => {
          const currentMode = newSourceSelections[source.id]
          const hasInsights = source.insights_count > 0

          if (currentMode === undefined) {
            // Initial setup - default based on insights availability
            newSourceSelections[source.id] = hasInsights ? 'insights' : 'full'
          } else if (currentMode === 'full' && hasInsights) {
            // Source gained insights while in 'full' mode - auto-switch to 'insights'
            newSourceSelections[source.id] = 'insights'
          }
        })
        return { ...prev, sources: newSourceSelections }
      })
    }
  }, [sources])

  useEffect(() => {
    if (notes && notes.length > 0) {
      setContextSelections(prev => {
        const newNoteSelections = { ...prev.notes }
        notes.forEach(note => {
          // Only set default if not already set
          if (!(note.id in newNoteSelections)) {
            // Notes default to 'full'
            newNoteSelections[note.id] = 'full'
          }
        })
        return { ...prev, notes: newNoteSelections }
      })
    }
  }, [notes])

  // Handler to update context selection
  const handleContextModeChange = (itemId: string, mode: ContextMode, type: 'source' | 'note') => {
    setContextSelections(prev => ({
      ...prev,
      [type === 'source' ? 'sources' : 'notes']: {
        ...(type === 'source' ? prev.sources : prev.notes),
        [itemId]: mode
      }
    }))
  }

  if (notebookLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (!notebook) {
    return (
      <AppShell>
        <div className="p-6">
          <h1 className="text-2xl font-bold mb-4">{t('notebooks.notFound')}</h1>
          <p className="text-muted-foreground">{t('notebooks.notFoundDesc')}</p>
        </div>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <div className="flex flex-col flex-1 min-h-0">
        <div className="flex-shrink-0 p-6 pb-0">
          <NotebookHeader notebook={notebook} />
        </div>

        <div className="flex-1 p-6 pt-6 overflow-x-auto flex flex-col">
          {/* Mobile: Tabbed interface - only render on mobile to avoid double-mounting */}
          {!isDesktop && (
            <>
              <div className="lg:hidden mb-4">
                <Tabs value={mobileActiveTab} onValueChange={(value) => setMobileActiveTab(value as 'sources' | 'chat' | 'preview')}>
                  <TabsList className="grid w-full grid-cols-3">
                    <TabsTrigger value="sources" className="gap-2">
                      <FileText className="h-4 w-4" />
                      {t('navigation.sources')}
                    </TabsTrigger>
                    <TabsTrigger value="chat" className="gap-2">
                      <MessageSquare className="h-4 w-4" />
                      {t('common.chat')}
                    </TabsTrigger>
                    <TabsTrigger value="preview" className="gap-2">
                      <FileOutput className="h-4 w-4" />
                      {t('common.preview')}
                    </TabsTrigger>
                  </TabsList>
                </Tabs>
              </div>

              {/* Mobile: Show only active tab */}
              <div className="flex-1 overflow-hidden lg:hidden">
                {mobileActiveTab === 'sources' && (
                  <SourcesColumn
                    sources={sources}
                    isLoading={sourcesLoading}
                    notebookId={notebookId}
                    notebookName={notebook?.name}
                    onRefresh={refetchSources}
                    contextSelections={contextSelections.sources}
                    onContextModeChange={(sourceId, mode) => handleContextModeChange(sourceId, mode, 'source')}
                    hasNextPage={hasNextPage}
                    isFetchingNextPage={isFetchingNextPage}
                    fetchNextPage={fetchNextPage}
                    onSendToPreview={setPreviewSource}
                  />
                )}
                {mobileActiveTab === 'chat' && (
                  <ChatColumn
                    notebookId={notebookId}
                    contextSelections={contextSelections}
                    sources={sources}
                    sourcesLoading={sourcesLoading}
                  />
                )}
                {mobileActiveTab === 'preview' && (
                  <PreviewColumn
                    notebookId={notebookId}
                    notebookName={notebook?.name}
                    previewSource={previewSource}
                    onPreviewSourceChange={setPreviewSource}
                  />
                )}
              </div>
            </>
          )}

          {/* Desktop: All three columns in a single resizable PanelGroup */}
          <PanelGroup orientation="horizontal" className="hidden lg:flex h-full min-h-0">
            {/* Sources Panel – slightly wider default */}
            <Panel
              panelRef={sourcePanelRef}
              defaultSize={28}
              minSize={5}
              collapsible
              collapsedSize="48px"
              onResize={(size) => {
                if (skipPanelSync.current) return
                const collapsed = size.inPixels <= 50
                if (collapsed !== useNotebookColumnsStore.getState().sourcesCollapsed) {
                  setSources(collapsed)
                }
              }}
            >
              <div className="h-full pr-1">
                <SourcesColumn
                  sources={sources}
                  isLoading={sourcesLoading}
                  notebookId={notebookId}
                  notebookName={notebook?.name}
                  onRefresh={refetchSources}
                  contextSelections={contextSelections.sources}
                  onContextModeChange={(sourceId, mode) => handleContextModeChange(sourceId, mode, 'source')}
                  hasNextPage={hasNextPage}
                  isFetchingNextPage={isFetchingNextPage}
                  fetchNextPage={fetchNextPage}
                  onSendToPreview={setPreviewSource}
                />
              </div>
            </Panel>

            {/* Resize handle: Sources ↔ Chat */}
            <PanelResizeHandle className="w-2 flex items-center justify-center group cursor-col-resize">
              <div className="w-0.5 h-12 rounded-full bg-border group-hover:bg-primary group-active:bg-primary transition-colors" />
            </PanelResizeHandle>

            {/* Chat Panel */}
            <Panel defaultSize={37} minSize={20}>
              <div className="h-full px-1">
                <ChatColumn
                  notebookId={notebookId}
                  contextSelections={contextSelections}
                  sources={sources}
                  sourcesLoading={sourcesLoading}
                />
              </div>
            </Panel>

            {/* Resize handle: Chat ↔ Preview */}
            <PanelResizeHandle className="w-2 flex items-center justify-center group cursor-col-resize">
              <div className="w-0.5 h-12 rounded-full bg-border group-hover:bg-primary group-active:bg-primary transition-colors" />
            </PanelResizeHandle>

            {/* Preview Panel */}
            <Panel
              panelRef={previewPanelRef}
              defaultSize={35}
              minSize={5}
              collapsible
              collapsedSize="48px"
              onResize={(size) => {
                if (skipPanelSync.current) return
                const collapsed = size.inPixels <= 50
                if (collapsed !== useNotebookColumnsStore.getState().previewCollapsed) {
                  setPreview(collapsed)
                }
              }}
            >
              <div className="h-full pl-1">
                <PreviewColumn
                  notebookId={notebookId}
                  notebookName={notebook?.name}
                  previewSource={previewSource}
                  onPreviewSourceChange={setPreviewSource}
                />
              </div>
            </Panel>
          </PanelGroup>
        </div>
      </div>
    </AppShell>
  )
}
