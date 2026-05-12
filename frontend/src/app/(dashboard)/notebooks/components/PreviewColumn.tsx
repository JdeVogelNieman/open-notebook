'use client'

import { useMemo, useState, useRef, useCallback, useEffect } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { FileOutput, FileText, Download, Loader2, X, AlertCircle } from 'lucide-react'
import { CollapsibleColumn, createCollapseButton } from '@/components/notebooks/CollapsibleColumn'
import { useNotebookColumnsStore } from '@/lib/stores/notebook-columns-store'
import { useTranslation } from '@/lib/hooks/use-translation'
import { SourceListResponse } from '@/lib/types/api'
import { sourcesApi } from '@/lib/api/sources'
import { cn } from '@/lib/utils'

interface PreviewColumnProps {
  notebookId: string
  notebookName?: string
  previewSource?: SourceListResponse | null
  onPreviewSourceChange?: (source: SourceListResponse | null) => void
}

/** Drop zone overlay shown when user is dragging a file over the preview column */
function DropOverlay() {
  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center bg-primary/10 border-2 border-dashed border-primary rounded-lg pointer-events-none">
      <div className="text-center">
        <FileText className="h-10 w-10 text-primary mx-auto mb-2" />
        <p className="text-sm font-medium text-primary">Sleep bestand hierheen</p>
      </div>
    </div>
  )
}

/** Renders a PDF source in an iframe using a blob URL */
function PdfViewer({ blobUrl }: { blobUrl: string }) {
  return (
    <iframe
      src={blobUrl}
      className="w-full h-full min-h-[600px] border-0 rounded"
      title="PDF Preview"
    />
  )
}

/** Renders a DOCX source inside a sandboxed iframe so docx-preview's global
 *  CSS/font injections are completely isolated from the main app's styles.
 *  The document is automatically scaled to fill the panel width whenever
 *  the panel is resized. */
function DocxViewer({ arrayBuffer }: { arrayBuffer: ArrayBuffer }) {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [rendering, setRendering] = useState(true)
  // Stores the page's natural pixel width after first render so the ResizeObserver
  // can recalculate zoom without resetting the DOM.
  const naturalPageWidthRef = useRef(0)

  /** Recalculate and apply CSS zoom so the document fills the panel width. */
  const applyZoom = useCallback(() => {
    const iframe = iframeRef.current
    if (!iframe || naturalPageWidthRef.current === 0) return
    const iframeWidth = iframe.offsetWidth
    if (iframeWidth === 0) return
    const zoom = Math.min((iframeWidth - 24) / naturalPageWidthRef.current, 1)
    const wrapper = iframe.contentDocument?.querySelector(
      '.docx-preview-wrapper'
    ) as HTMLElement | null
    if (wrapper) {
      // CSS zoom reflows layout so the scrollable area matches the scaled size
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ;(wrapper as any).style.zoom = `${Math.round(zoom * 100)}%`
    }
  }, [])

  useEffect(() => {
    const iframe = iframeRef.current
    if (!iframe || !arrayBuffer) return

    let cancelled = false
    setRendering(true)
    setError(null)
    naturalPageWidthRef.current = 0

    // Read the actual computed card background from a temporary Tailwind element.
    // We append it, read getComputedStyle (which gives a real rgb() value), then remove it.
    const tempEl = document.createElement('div')
    tempEl.className = 'bg-card'
    tempEl.style.cssText = 'position:fixed;top:-9999px;left:-9999px;width:1px;height:1px;'
    document.body.appendChild(tempEl)
    const bgColor = getComputedStyle(tempEl).backgroundColor || '#ffffff'
    document.body.removeChild(tempEl)

    // Bootstrap the iframe document
    const iframeDoc = iframe.contentDocument
    if (!iframeDoc) return
    iframeDoc.open()
    iframeDoc.write(`<!DOCTYPE html><html><head>
      <meta charset="utf-8"/>
      <style>
        html, body {
          margin: 0; padding: 0;
          overflow-y: scroll;
          overflow-x: hidden;
          scrollbar-gutter: stable;
        }
        .docx-preview-wrapper {
          padding: 16px 0 !important;
        }
        .docx-preview-wrapper section.docx-preview {
          box-shadow: 0 1px 6px rgba(0,0,0,0.18);
          margin: 0 auto;
        }
      </style>
    </head><body><div id="root"></div></body></html>`)
    iframeDoc.close()

    const container = iframeDoc.getElementById('root')
    if (!container) return

    import('docx-preview').then(({ renderAsync }) => {
      if (cancelled) return
      return renderAsync(arrayBuffer, container, iframeDoc.head, {
        className: 'docx-preview',
        inWrapper: true,
        ignoreWidth: false,
        ignoreHeight: false,
        ignoreFonts: false,
        breakPages: true,
        experimental: true,
        renderHeaders: true,
        renderFooters: true,
        renderFootnotes: true,
        renderEndnotes: true,
        useBase64URL: true,
      })
    }).then(() => {
      if (cancelled) return

      // Inject background AFTER docx-preview so our rule wins in cascade order.
      const bgStyle = iframeDoc.createElement('style')
      bgStyle.textContent = `
        html, body { background: ${bgColor} !important; }
        .docx-preview-wrapper { background: ${bgColor} !important; }
      `
      iframeDoc.head.appendChild(bgStyle)

      // Measure natural page width at 100 % zoom
      const page = iframeDoc.querySelector(
        '.docx-preview-wrapper section.docx-preview'
      ) as HTMLElement | null
      naturalPageWidthRef.current = page?.offsetWidth ?? 794

      setRendering(false)
    }).catch((err) => {
      if (!cancelled) {
        setError(err?.message ?? 'Render error')
        setRendering(false)
      }
    })

    return () => { cancelled = true }
  }, [arrayBuffer])

  // After rendering, apply initial zoom and watch the iframe for resize events
  // (triggered whenever the user drags the panel separator).
  useEffect(() => {
    if (rendering) return
    applyZoom()

    const iframe = iframeRef.current
    if (!iframe) return
    const ro = new ResizeObserver(applyZoom)
    ro.observe(iframe)
    return () => ro.disconnect()
  }, [rendering, applyZoom])

  if (error) {
    return (
      <div className="flex items-center gap-2 text-destructive text-sm p-4">
        <AlertCircle className="h-4 w-4" />
        <span>Kon document niet weergeven: {error}</span>
      </div>
    )
  }

  return (
    <div className="relative w-full h-full flex flex-col">
      {rendering && (
        <div className="absolute inset-0 flex items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )}
      <iframe
        ref={iframeRef}
        className={cn('w-full border-0', rendering ? 'invisible flex-1' : 'flex-1')}
        title="DOCX Preview"
      />
    </div>
  )
}

export function PreviewColumn({
  notebookId,
  notebookName,
  previewSource,
  onPreviewSourceChange,
}: PreviewColumnProps) {
  const { t } = useTranslation()
  const { previewCollapsed, togglePreview } = useNotebookColumnsStore()

  const [isDragOver, setIsDragOver] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [pdfBlobUrl, setPdfBlobUrl] = useState<string | null>(null)
  const [docxBuffer, setDocxBuffer] = useState<ArrayBuffer | null>(null)
  const [loadedSource, setLoadedSource] = useState<SourceListResponse | null>(null)

  const collapseButton = useMemo(
    () => createCollapseButton(togglePreview, t('common.preview')),
    [togglePreview, t]
  )

  // Load the file whenever previewSource changes
  useEffect(() => {
    if (!previewSource) {
      setPdfBlobUrl(null)
      setDocxBuffer(null)
      setLoadedSource(null)
      setLoadError(null)
      return
    }

    // Revoke previous blob URL
    if (pdfBlobUrl) URL.revokeObjectURL(pdfBlobUrl)
    setPdfBlobUrl(null)
    setDocxBuffer(null)
    setLoadError(null)
    setIsLoading(true)
    setLoadedSource(previewSource)

    const fileExt = previewSource.asset?.file_path?.split('.').pop()?.toLowerCase() ?? ''

    sourcesApi.downloadFile(previewSource.id)
      .then(async (response) => {
        const blob: Blob = response.data
        if (fileExt === 'pdf') {
          const url = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }))
          setPdfBlobUrl(url)
        } else if (fileExt === 'docx' || fileExt === 'doc') {
          const buffer = await blob.arrayBuffer()
          setDocxBuffer(buffer)
        }
      })
      .catch((err) => {
        setLoadError(err?.message ?? 'Ophalen mislukt')
      })
      .finally(() => {
        setIsLoading(false)
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewSource])

  // Cleanup blob URL on unmount
  useEffect(() => {
    return () => {
      if (pdfBlobUrl) URL.revokeObjectURL(pdfBlobUrl)
    }
  }, [pdfBlobUrl])

  const handleDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragOver(false)
    const raw = e.dataTransfer.getData('application/json')
    if (!raw) return
    try {
      const source: SourceListResponse = JSON.parse(raw)
      onPreviewSourceChange?.(source)
    } catch {
      // ignore
    }
  }, [onPreviewSourceChange])

  const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
    setIsDragOver(true)
  }, [])

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false)
  }, [])

  const handleClear = () => {
    onPreviewSourceChange?.(null)
  }

  const handleDownload = () => {
    if (!loadedSource) return
    sourcesApi.downloadFile(loadedSource.id).then((response) => {
      const url = URL.createObjectURL(response.data)
      const a = document.createElement('a')
      a.href = url
      a.download = loadedSource.title ?? 'download'
      a.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    })
  }

  const fileExt = loadedSource?.asset?.file_path?.split('.').pop()?.toLowerCase() ?? ''
  const hasContent = !!loadedSource

  return (
    <CollapsibleColumn
      isCollapsed={previewCollapsed}
      onToggle={togglePreview}
      collapsedIcon={FileOutput}
      collapsedLabel={t('common.preview')}
    >
      <Card
        className={cn('h-full flex flex-col flex-1 overflow-hidden relative')}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
      >
        {isDragOver && <DropOverlay />}

        <CardHeader className="pb-3 flex-shrink-0">
          <div className="flex items-center justify-between gap-2">
            <CardTitle className="text-lg">{t('common.preview')}</CardTitle>
            <div className="flex items-center gap-2">
              {hasContent && (
                <>
                  <Button variant="ghost" size="sm" onClick={handleDownload} title="Download" className="h-8 w-8 p-0">
                    <Download className="h-4 w-4" />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={handleClear} title="Sluiten" className="h-8 w-8 p-0">
                    <X className="h-4 w-4" />
                  </Button>
                </>
              )}
              {collapseButton}
            </div>
          </div>

          {/* File info bar */}
          {loadedSource && (
            <div className="flex items-center gap-2 mt-1">
              <FileText className="h-4 w-4 text-muted-foreground flex-shrink-0" />
              <span className="text-sm truncate text-muted-foreground" title={loadedSource.title ?? ''}>
                {loadedSource.title}
              </span>
              <Badge variant="secondary" className="text-xs uppercase flex-shrink-0">
                {fileExt}
              </Badge>
            </div>
          )}
        </CardHeader>

        <CardContent className="flex-1 overflow-y-auto min-h-0 p-3">
          {isLoading ? (
            <div className="flex items-center justify-center h-full">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : loadError ? (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
              <AlertCircle className="h-8 w-8 text-destructive" />
              <p className="text-sm text-destructive">{loadError}</p>
              <Button variant="outline" size="sm" onClick={handleDownload}>
                <Download className="h-4 w-4 mr-2" />
                Download bestand
              </Button>
            </div>
          ) : pdfBlobUrl ? (
            <PdfViewer blobUrl={pdfBlobUrl} />
          ) : docxBuffer ? (
            <DocxViewer arrayBuffer={docxBuffer} />
          ) : hasContent ? (
            // Unsupported file type - show download fallback
            <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
              <FileText className="h-10 w-10 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                Bestandstype <strong>.{fileExt}</strong> kan niet worden weergegeven.
              </p>
              <Button variant="outline" size="sm" onClick={handleDownload}>
                <Download className="h-4 w-4 mr-2" />
                Download bestand
              </Button>
            </div>
          ) : (
            // Empty state – prompt user to drop a PDF or DOCX from the sources panel
            <div className="flex flex-col items-center justify-center h-full gap-3 text-center text-muted-foreground">
              <FileOutput className="h-12 w-12 opacity-30" />
              <p className="text-sm font-medium">Geen document geladen</p>
              <p className="text-xs opacity-70 max-w-[200px]">
                Sleep een PDF of Word-bestand vanuit het bronnenvenster hiernaartoe, of klik op het oogpictogram op een bronkaart.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </CollapsibleColumn>
  )
}

