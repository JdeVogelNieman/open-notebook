'use client'

import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import { useSettings, useUpdateSettings } from '@/lib/hooks/use-settings'
import { useEffect, useState } from 'react'
import { ChevronDownIcon } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import apiClient from '@/lib/api/client'

const settingsSchema = z.object({
  default_content_processing_engine_doc: z.enum(['auto', 'docling', 'simple']).optional(),
  default_content_processing_engine_url: z.enum(['auto', 'firecrawl', 'jina', 'simple']).optional(),
  default_embedding_option: z.enum(['ask', 'always', 'never']).optional(),
  auto_delete_files: z.enum(['yes', 'no']).optional(),
  rag_enabled: z.boolean().optional(),
  rag_service_url: z.string().optional(),
  rag_base_dir: z.string().optional(),
  rag_max_results: z.number().int().min(1).max(20).optional(),
})

type SettingsFormData = z.infer<typeof settingsSchema>

export function SettingsForm() {
  const { t } = useTranslation()
  const { data: settings, isLoading, error } = useSettings()
  const updateSettings = useUpdateSettings()
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    doc: false,
    url: false,
    embedding: false,
    files: false
  })
  const [hasResetForm, setHasResetForm] = useState(false)
  const [ragTestStatus, setRagTestStatus] = useState<'idle' | 'testing' | 'ok' | 'error'>('idle')
  const [ragTestMessage, setRagTestMessage] = useState('')
  
  
  const {
    control,
    handleSubmit,
    reset,
    watch,
    formState: { isDirty }
  } = useForm<SettingsFormData>({
    resolver: zodResolver(settingsSchema),
    defaultValues: {
      default_content_processing_engine_doc: undefined,
      default_content_processing_engine_url: undefined,
      default_embedding_option: undefined,
      auto_delete_files: undefined,
      rag_enabled: false,
      rag_service_url: 'http://host.docker.internal:3001',
      rag_base_dir: '',
      rag_max_results: 3,
    }
  })


  const toggleSection = (section: string) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }))
  }

  useEffect(() => {
    if (settings && !hasResetForm) {
      const formData = {
        default_content_processing_engine_doc: settings.default_content_processing_engine_doc as 'auto' | 'docling' | 'simple',
        default_content_processing_engine_url: settings.default_content_processing_engine_url as 'auto' | 'firecrawl' | 'jina' | 'simple',
        default_embedding_option: settings.default_embedding_option as 'ask' | 'always' | 'never',
        auto_delete_files: settings.auto_delete_files as 'yes' | 'no',
        rag_enabled: settings.rag_enabled ?? false,
        rag_service_url: settings.rag_service_url ?? 'http://host.docker.internal:3001',
        rag_base_dir: settings.rag_base_dir ?? '',
        rag_max_results: settings.rag_max_results ?? 3,
      }
      reset(formData)
      setHasResetForm(true)
    }
  }, [hasResetForm, reset, settings])

  const onSubmit = async (data: SettingsFormData) => {
    await updateSettings.mutateAsync(data)
  }

  const testRagConnection = async () => {
    const url = watch('rag_service_url') || 'http://host.docker.internal:3001'
    setRagTestStatus('testing')
    setRagTestMessage('')
    try {
      const resp = await apiClient.get(`/rag/status?url=${encodeURIComponent(url)}`)
      const data = resp.data as { available: boolean; details?: { documentCount?: number } }
      if (data.available) {
        const docs = data.details?.documentCount ?? '?'
        setRagTestStatus('ok')
        setRagTestMessage(`Connected — ${docs} documents indexed`)
      } else {
        setRagTestStatus('error')
        setRagTestMessage('Service unreachable')
      }
    } catch {
      setRagTestStatus('error')
      setRagTestMessage('Could not reach RAG service')
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTitle>{t('settings.loadFailed')}</AlertTitle>
        <AlertDescription>
          {error instanceof Error ? error.message : t('common.error')}
        </AlertDescription>
      </Alert>
    )
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t('settings.contentProcessing')}</CardTitle>
          <CardDescription>
            {t('settings.contentProcessingDesc')}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-3">
            <Label htmlFor="doc_engine">{t('settings.docEngine')}</Label>
            <Controller
              name="default_content_processing_engine_doc"
              control={control}
              render={({ field }) => (
                  <Select
                    key={field.value}
                    name={field.name}
                    value={field.value || ''}
                    onValueChange={field.onChange}
                    disabled={field.disabled || isLoading}
                  >
                      <SelectTrigger id="doc_engine" className="w-full">
                        <SelectValue placeholder={t('settings.docEnginePlaceholder')} />
                      </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">{t('settings.autoRecommended')}</SelectItem>
                      <SelectItem value="docling">{t('settings.docling')}</SelectItem>
                      <SelectItem value="simple">{t('settings.simple')}</SelectItem>
                    </SelectContent>
                  </Select>
              )}
            />
            <Collapsible open={expandedSections.doc} onOpenChange={() => toggleSection('doc')}>
              <CollapsibleTrigger className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors">
                <ChevronDownIcon className={`h-4 w-4 transition-transform ${expandedSections.doc ? 'rotate-180' : ''}`} />
                {t('settings.helpMeChoose')}
              </CollapsibleTrigger>
              <CollapsibleContent className="mt-2 text-sm text-muted-foreground space-y-2">
                <p>{t('settings.docHelp')}</p>
              </CollapsibleContent>
            </Collapsible>
          </div>
          
          <div className="space-y-3">
            <Label htmlFor="url_engine">{t('settings.urlEngine')}</Label>
            <Controller
              name="default_content_processing_engine_url"
              control={control}
              render={({ field }) => (
                <Select
                  key={field.value}
                  name={field.name}
                  value={field.value || ''}
                  onValueChange={field.onChange}
                  disabled={field.disabled || isLoading}
                >
                  <SelectTrigger id="url_engine" className="w-full">
                    <SelectValue placeholder={t('settings.urlEnginePlaceholder')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">{t('settings.autoRecommended')}</SelectItem>
                    <SelectItem value="firecrawl">{t('settings.firecrawl')}</SelectItem>
                    <SelectItem value="jina">{t('settings.jina')}</SelectItem>
                    <SelectItem value="simple">{t('settings.simple')}</SelectItem>
                  </SelectContent>
                </Select>
              )}
            />
             <Collapsible open={expandedSections.url} onOpenChange={() => toggleSection('url')}>
              <CollapsibleTrigger className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors">
                <ChevronDownIcon className={`h-4 w-4 transition-transform ${expandedSections.url ? 'rotate-180' : ''}`} />
                {t('settings.helpMeChoose')}
              </CollapsibleTrigger>
              <CollapsibleContent className="mt-2 text-sm text-muted-foreground space-y-2">
                <p>{t('settings.urlHelp')}</p>
              </CollapsibleContent>
            </Collapsible>
          </div>
        </CardContent>
      </Card>

       <Card>
        <CardHeader>
          <CardTitle>{t('settings.embeddingAndSearch')}</CardTitle>
          <CardDescription>
            {t('settings.embeddingAndSearchDesc')}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
           <div className="space-y-3">
            <Label htmlFor="embedding">{t('settings.defaultEmbeddingOption')}</Label>
            <Controller
              name="default_embedding_option"
              control={control}
              render={({ field }) => (
                <Select
                  key={field.value}
                  name={field.name}
                  value={field.value || ''}
                  onValueChange={field.onChange}
                  disabled={field.disabled || isLoading}
                >
                  <SelectTrigger id="embedding" className="w-full">
                    <SelectValue placeholder={t('settings.embeddingOptionPlaceholder')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ask">{t('settings.ask')}</SelectItem>
                    <SelectItem value="always">{t('settings.always')}</SelectItem>
                    <SelectItem value="never">{t('settings.never')}</SelectItem>
                  </SelectContent>
                </Select>
              )}
            />
             <Collapsible open={expandedSections.embedding} onOpenChange={() => toggleSection('embedding')}>
              <CollapsibleTrigger className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors">
                <ChevronDownIcon className={`h-4 w-4 transition-transform ${expandedSections.embedding ? 'rotate-180' : ''}`} />
                {t('settings.helpMeChoose')}
              </CollapsibleTrigger>
              <CollapsibleContent className="mt-2 text-sm text-muted-foreground space-y-2">
                <p>{t('settings.embeddingHelp')}</p>
              </CollapsibleContent>
            </Collapsible>
          </div>
        </CardContent>
      </Card>

       <Card>
        <CardHeader>
          <CardTitle>{t('settings.fileManagement')}</CardTitle>
          <CardDescription>
            {t('settings.fileManagementDesc')}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
           <div className="space-y-3">
            <Label htmlFor="auto_delete">{t('settings.autoDeleteFiles')}</Label>
            <Controller
              name="auto_delete_files"
              control={control}
              render={({ field }) => (
                <Select
                  key={field.value}
                  name={field.name}
                  value={field.value || ''}
                  onValueChange={field.onChange}
                  disabled={field.disabled || isLoading}
                >
                  <SelectTrigger id="auto_delete" className="w-full">
                    <SelectValue placeholder={t('settings.autoDeletePlaceholder')} />
                  </SelectTrigger>
                   <SelectContent>
                    <SelectItem value="yes">{t('common.yes')}</SelectItem>
                    <SelectItem value="no">{t('common.no')}</SelectItem>
                  </SelectContent>
                </Select>
              )}
            />
             <Collapsible open={expandedSections.files} onOpenChange={() => toggleSection('files')}>
              <CollapsibleTrigger className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors">
                <ChevronDownIcon className={`h-4 w-4 transition-transform ${expandedSections.files ? 'rotate-180' : ''}`} />
                {t('settings.helpMeChoose')}
              </CollapsibleTrigger>
              <CollapsibleContent className="mt-2 text-sm text-muted-foreground space-y-2">
                <p>{t('settings.filesHelp')}</p>
              </CollapsibleContent>
            </Collapsible>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Local RAG Integration</CardTitle>
          <CardDescription>
            Connect to NiemanLocalRag to automatically add relevant documents to your notebook during chat.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-3">
            <Controller
              name="rag_enabled"
              control={control}
              render={({ field }) => (
                <Checkbox
                  id="rag_enabled"
                  checked={field.value ?? false}
                  onCheckedChange={field.onChange}
                />
              )}
            />
            <Label htmlFor="rag_enabled">Enable RAG</Label>
          </div>

          <div className="space-y-2">
            <Label htmlFor="rag_service_url">RAG Service URL</Label>
            <div className="flex gap-2">
              <Controller
                name="rag_service_url"
                control={control}
                render={({ field }) => (
                  <Input
                    id="rag_service_url"
                    placeholder="http://host.docker.internal:3001"
                    {...field}
                    value={field.value ?? ''}
                  />
                )}
              />
              <Button type="button" variant="outline" onClick={testRagConnection} disabled={ragTestStatus === 'testing'}>
                {ragTestStatus === 'testing' ? 'Testing…' : 'Test'}
              </Button>
            </div>
            {ragTestStatus === 'ok' && (
              <p className="text-sm text-green-600">{ragTestMessage}</p>
            )}
            {ragTestStatus === 'error' && (
              <p className="text-sm text-destructive">{ragTestMessage}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="rag_base_dir">Base Directory (on host)</Label>
            <Controller
              name="rag_base_dir"
              control={control}
              render={({ field }) => (
                <Input
                  id="rag_base_dir"
                  placeholder="C:\Users\...\Downloads\base"
                  {...field}
                  value={field.value ?? ''}
                />
              )}
            />
            <p className="text-xs text-muted-foreground">The folder path on your host machine where documents are stored.</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="rag_max_results">Max Results per Query</Label>
            <Controller
              name="rag_max_results"
              control={control}
              render={({ field }) => (
                <Input
                  id="rag_max_results"
                  type="number"
                  min={1}
                  max={20}
                  {...field}
                  value={field.value ?? 3}
                  onChange={(e) => field.onChange(parseInt(e.target.value, 10) || 3)}
                />
              )}
            />
          </div>
        </CardContent>
      </Card>

      <div className="flex justify-end">
         <Button 
          type="submit" 
          disabled={!isDirty || updateSettings.isPending}
        >
          {updateSettings.isPending ? t('common.saving') : t('navigation.settings')}
        </Button>
      </div>
    </form>
  )
}
