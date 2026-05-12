'use client'

import { useMemo } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { FileOutput, Clock } from 'lucide-react'
import { CollapsibleColumn, createCollapseButton } from '@/components/notebooks/CollapsibleColumn'
import { useNotebookColumnsStore } from '@/lib/stores/notebook-columns-store'
import { useTranslation } from '@/lib/hooks/use-translation'

interface PreviewColumnProps {
  notebookId: string
  notebookName?: string
}

/** Demo Word-style document shown as a placeholder until real output documents are generated. */
function DemoDocument() {
  const { t } = useTranslation()

  return (
    <div className="space-y-3 text-sm">
      {/* Demo badge */}
      <div className="flex items-center gap-2">
        <Badge variant="secondary" className="text-xs gap-1">
          <Clock className="h-3 w-3" />
          {t('notebooks.previewDemo')}
        </Badge>
      </div>

      {/* Word-style document */}
      <div
        className="bg-white text-gray-900 shadow-[0_2px_12px_rgba(0,0,0,0.18)] rounded-sm"
        style={{ fontFamily: '"Calibri", "Segoe UI", sans-serif' }}
      >
        {/* Document header strip */}
        <div className="bg-[#2E4057] text-white px-6 py-3 rounded-t-sm">
          <p className="text-[10px] uppercase tracking-widest text-blue-200 font-semibold">Nieman Raadgevend Ingenieurs</p>
          <p className="text-[10px] text-blue-200 mt-0.5">Bouwfysica · Technisch Rapport</p>
        </div>

        {/* Page body */}
        <div className="px-8 py-6 space-y-5">
          {/* Title block */}
          <div className="border-b-2 border-[#2E4057] pb-4">
            <h1 className="text-xl font-bold leading-snug text-[#2E4057]">
              AI-Gestuurde Databaseanalyse<br />voor Bouwfysische Optimalisatie
            </h1>
            <p className="text-xs text-gray-500 mt-2">
              Auteur: Nieman Analysesysteem &nbsp;·&nbsp; Datum: 11 mei 2026 &nbsp;·&nbsp; Versie 1.0
            </p>
          </div>

          {/* Samenvatting */}
          <div>
            <h2 className="text-[13px] font-bold text-[#2E4057] uppercase tracking-wide mb-1.5">
              1. Samenvatting
            </h2>
            <p className="text-[13px] leading-relaxed text-gray-700">
              Dit technische rapport presenteert een AI-gegenereerde analyse van bouwfysische prestaties 
              afgeleid uit gekoppelde databases. Het onderzoek integreert sensorgegevens, thermische 
              metingen, energiebilansen en simulatieresultaten. De AI heeft patronen en prestatiefouten 
              in vier bouwprojecten geïdentificeerd en aanbevelingen voor optimalisatie afgeleid.
            </p>
          </div>

          {/* Bevindingen */}
          <div>
            <h2 className="text-[13px] font-bold text-[#2E4057] uppercase tracking-wide mb-1.5">
              2. Belangrijkste Bevindingen
            </h2>
            <ul className="space-y-1.5 text-[13px] text-gray-700">
              {[
                'Vochtproblemen in buitenwanden: 38% van de geanalyseerde locaties overschrijdt de kritieke drempel van 60% RH in kritieke zones gedurende >4 maanden per jaar.',
                'Significante warmtebruggen gedetecteerd: gemiddeld 4-6°C oppervlaktetemperatuurverschil bij hoeken en consoles, verhoogt condensatierisico\'s aanzienlijk.',
                'Luchtdichtheidsgebreken variëren sterk: gebouwen A & B voldoen aan normen (≤3 m³/(h·m²)), terwijl C & D substantiële lekkages vertonen (8-12 m³/(h·m²)).',
              ].map((item, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-[#2E4057] font-bold flex-shrink-0">{i + 1}.</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Analyse */}
          <div>
            <h2 className="text-[13px] font-bold text-[#2E4057] uppercase tracking-wide mb-1.5">
              3. Analyse
            </h2>
            <p className="text-[13px] leading-relaxed text-gray-700">
              De koppeling van disparate databases via het AI-platform creëert een unified view op 
              bouwfysische performance. Het algoritme detecteert statistische anomalieën en 
              correlaties tussen bouwgeometrie, materiaalspecificaties, invoergegevens en 
              prestatiewerkelijkheid—zonder menselijke voorbias. Dit stelt projectteams in staat 
              causaliteit vast te stellen en prioriteiten op basis van data in plaats van hypothese.
            </p>
          </div>

          {/* Aanbevelingen */}
          <div>
            <h2 className="text-[13px] font-bold text-[#2E4057] uppercase tracking-wide mb-1.5">
              4. Aanbevelingen
            </h2>
            <ol className="space-y-1.5 text-[13px] text-gray-700 list-decimal list-inside">
              <li>Monitoren uitbreiden: vochtmeting en thermische sensoren installeren in kritieke zones (hoeken, balklagen, voegen).</li>
              <li>Data governance protocol opstellen: kalibratiestandaarden, sensoronderhoudsprotocol, data-eigenaarschap bepalen.</li>
              <li>Interventies prioriteren: focus op warmtebrug-remedies en luchtdichtingswerk met hoogste impact/kostverhouding.</li>
              <li>Verificatie: herhaalde metingen 6 en 12 maanden na ingrepen om leereffect en persistentie vast te stellen.</li>
            </ol>
          </div>

          {/* Footer line */}
          <div className="border-t border-gray-200 pt-3 flex items-center justify-between text-[10px] text-gray-400">
            <span>Databases verwerkt: 4 &nbsp;·&nbsp; Notities gebruikt: 2</span>
            <span>Pagina 1 van 1</span>
          </div>
        </div>
      </div>

      <p className="text-xs text-muted-foreground italic text-center">
        {t('notebooks.previewDemoHint')}
      </p>
    </div>
  )
}

export function PreviewColumn({ notebookId, notebookName }: PreviewColumnProps) {
  const { t } = useTranslation()
  const { previewCollapsed, togglePreview } = useNotebookColumnsStore()

  const collapseButton = useMemo(
    () => createCollapseButton(togglePreview, t('common.preview')),
    [togglePreview, t]
  )

  return (
    <CollapsibleColumn
      isCollapsed={previewCollapsed}
      onToggle={togglePreview}
      collapsedIcon={FileOutput}
      collapsedLabel={t('common.preview')}
    >
      <Card className="h-full flex flex-col flex-1 overflow-hidden">
        <CardHeader className="pb-3 flex-shrink-0">
          <div className="flex items-center justify-between gap-2">
            <CardTitle className="text-lg">{t('common.preview')}</CardTitle>
            <div className="flex items-center gap-2">
              {collapseButton}
            </div>
          </div>
        </CardHeader>

        <CardContent className="flex-1 overflow-y-auto min-h-0">
          <DemoDocument />
        </CardContent>
      </Card>
    </CollapsibleColumn>
  )
}

