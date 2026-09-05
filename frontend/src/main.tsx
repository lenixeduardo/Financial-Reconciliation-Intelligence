import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import {
  ArrowLeftRight, ArrowRight, BarChart3, Bell, BookmarkPlus, Building2, Check,
  CheckCircle2, ChevronRight, CircleAlert, CircleX, Database, Download,
  FileSpreadsheet, FileWarning, GitCompareArrows, Home, Layers3, Menu, Moon,
  MoreHorizontal, RefreshCw, Search, Settings, Settings2, ShieldCheck, SlidersHorizontal,
  Sun, Trash2, Upload, X
} from 'lucide-react'
import './styles.css'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

type Dataset = {
  dataset_id: string; label: string; filename: string; rows: number;
  columns: string[]; preview: Record<string, unknown>[];
  suggested_mapping: Record<string, string | null>;
}

type Mapping = { amount: string; date: string; description: string; document: string }
type Rules = { amount_tolerance: number; date_tolerance_days: number; description_similarity: number; require_document_exact: boolean; auto_approve_threshold: number; probable_match_threshold: number; group_matching_enabled: boolean; max_group_size: number; group_match_threshold: number; group_candidate_limit: number }
type Template = {
  template_id: string; name: string; description?: string | null;
  left_mapping: { amount: string; date?: string | null; description?: string | null; document?: string | null };
  right_mapping: { amount: string; date?: string | null; description?: string | null; document?: string | null };
  rules: Rules; left_columns: string[]; right_columns: string[]; created_at: string; updated_at: string;
}
type Pair = {
  pair_id: string; status: string; confidence: number; match_cardinality: '1:1'|'1:N'|'N:1';
  left_indices: number[]; right_indices: number[];
  amount_left?: number; amount_right?: number; amount_difference?: number;
  date_left?: string; date_right?: string; description_left?: string; description_right?: string;
  document_left?: string; document_right?: string; reasons: string[];
  left_row?: Record<string, unknown> | null; right_row?: Record<string, unknown> | null;
  left_rows: Record<string, unknown>[]; right_rows: Record<string, unknown>[];
}
type Result = {
  summary: { reconciliation_id: string; total_left: number; total_right: number; matched: number; probable_matches: number; divergences: number; unmatched: number; duplicates: number; manual_review: number; one_to_many: number; many_to_one: number; grouped_matches: number; reconciled_left_rows: number; reconciled_right_rows: number; match_rate: number; total_amount_left: number; total_amount_right: number; net_difference: number };
  pairs: Pair[];
}

const emptyMapping: Mapping = { amount: '', date: '', description: '', document: '' }
const defaultRules: Rules = { amount_tolerance: 0, date_tolerance_days: 0, description_similarity: .82, require_document_exact: false, auto_approve_threshold: .95, probable_match_threshold: .75, group_matching_enabled: true, max_group_size: 3, group_match_threshold: .85, group_candidate_limit: 18 }

function mapFromDataset(ds: Dataset): Mapping {
  return {
    amount: ds.suggested_mapping.amount || ds.columns[0] || '',
    date: ds.suggested_mapping.date || '',
    description: ds.suggested_mapping.description || '',
    document: ds.suggested_mapping.document || '',
  }
}

function money(value: number) {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value || 0)
}

function statusLabel(status: string) {
  return ({ MATCH: 'Conciliado', PROBABLE_MATCH: 'Match provável', DIVERGENCE: 'Divergência', UNMATCHED: 'Não encontrado', DUPLICATE: 'Duplicado', APPROVED: 'Aprovado', REJECTED: 'Rejeitado' } as Record<string,string>)[status] || status
}

function UploadCard({ title, subtitle, dataset, onUpload }: { title: string; subtitle: string; dataset: Dataset | null; onUpload: (f: File)=>void }) {
  const input = useRef<HTMLInputElement>(null)
  return <button className="upload-card" onClick={() => input.current?.click()}>
    <input ref={input} type="file" accept=".csv,.xlsx,.xlsm" hidden onChange={e => e.target.files?.[0] && onUpload(e.target.files[0])} />
    <div className="upload-icon">{dataset ? <FileSpreadsheet size={22}/> : <Upload size={22}/>}</div>
    <div className="upload-copy">
      <strong>{dataset ? dataset.filename : title}</strong>
      <span>{dataset ? `${dataset.rows.toLocaleString('pt-BR')} registros • ${dataset.columns.length} colunas` : subtitle}</span>
    </div>
    {dataset ? <Check className="ok" size={20}/> : <ChevronRight size={18}/>} 
  </button>
}

function App() {
  const [dark, setDark] = useState(() => localStorage.getItem('fri-theme') === 'dark')
  const [left, setLeft] = useState<Dataset|null>(null)
  const [right, setRight] = useState<Dataset|null>(null)
  const [leftMap, setLeftMap] = useState<Mapping>(emptyMapping)
  const [rightMap, setRightMap] = useState<Mapping>(emptyMapping)
  const [rules, setRules] = useState<Rules>(defaultRules)
  const [result, setResult] = useState<Result|null>(null)
  const [step, setStep] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('ALL')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<Pair|null>(null)
  const [templates, setTemplates] = useState<Template[]>([])
  const [templateSelectionId, setTemplateSelectionId] = useState('')
  const [activeTemplateId, setActiveTemplateId] = useState('')
  const [templateName, setTemplateName] = useState('')
  const [templateDescription, setTemplateDescription] = useState('')

  useEffect(() => { document.documentElement.dataset.theme = dark ? 'dark' : 'light'; localStorage.setItem('fri-theme', dark ? 'dark' : 'light') }, [dark])
  useEffect(() => { void loadTemplates() }, [])

  async function loadTemplates() {
    try {
      const res = await fetch(`${API}/templates`)
      if (!res.ok) return
      setTemplates(await res.json())
    } catch { /* API may still be starting */ }
  }

  async function upload(file: File, side: 'left'|'right') {
    setError(''); setLoading(true)
    const fd = new FormData(); fd.append('file', file); fd.append('label', side === 'left' ? 'Base principal' : 'Base de comparação')
    try {
      const res = await fetch(`${API}/datasets/upload`, { method: 'POST', body: fd })
      const body = await res.json(); if (!res.ok) throw new Error(body.detail || 'Falha no upload')
      if (side === 'left') { setLeft(body); setLeftMap(mapFromDataset(body)) } else { setRight(body); setRightMap(mapFromDataset(body)) }
    } catch (e) { setError(e instanceof Error ? e.message : 'Falha no upload') } finally { setLoading(false) }
  }

  async function run() {
    if (!left || !right || !leftMap.amount || !rightMap.amount) return
    setLoading(true); setError(''); setResult(null)
    try {
      const payload = { left_dataset_id: left.dataset_id, right_dataset_id: right.dataset_id, left_mapping: normMap(leftMap), right_mapping: normMap(rightMap), rules, template_id: activeTemplateId || null }
      const res = await fetch(`${API}/reconciliations`, { method: 'POST', headers: { 'Content-Type':'application/json' }, body: JSON.stringify(payload) })
      const body = await res.json(); if (!res.ok) throw new Error(body.detail || 'Falha ao executar conciliação')
      setResult(body); setStep(4)
    } catch (e) { setError(e instanceof Error ? e.message : 'Falha ao executar') } finally { setLoading(false) }
  }

  async function applyTemplate(templateId: string) {
    if (!left || !right || !templateId) return
    setLoading(true); setError('')
    try {
      const res = await fetch(`${API}/templates/${templateId}/apply`, {
        method: 'POST', headers: { 'Content-Type':'application/json' },
        body: JSON.stringify({ left_dataset_id:left.dataset_id, right_dataset_id:right.dataset_id })
      })
      const body = await res.json()
      if (!res.ok) throw new Error(body.detail || 'Falha ao aplicar template')
      if (!body.compatible) {
        const missing = [...body.missing_left_columns, ...body.missing_right_columns].join(', ')
        throw new Error(`Template incompatível. Colunas ausentes: ${missing}`)
      }
      const tpl = body.template as Template
      setLeftMap(fromApiMap(tpl.left_mapping)); setRightMap(fromApiMap(tpl.right_mapping)); setRules(tpl.rules)
      setTemplateSelectionId(tpl.template_id); setActiveTemplateId(tpl.template_id); setTemplateName(tpl.name); setTemplateDescription(tpl.description || '')
    } catch (e) { setError(e instanceof Error ? e.message : 'Falha ao aplicar template') } finally { setLoading(false) }
  }

  async function saveTemplate(updateExisting = false) {
    if (!left || !right || !leftMap.amount || !rightMap.amount || !templateName.trim()) {
      setError('Informe um nome e conclua o mapeamento antes de salvar o template.')
      return
    }
    setLoading(true); setError('')
    try {
      const payload = {
        name: templateName.trim(), description: templateDescription.trim() || null,
        left_mapping: normMap(leftMap), right_mapping: normMap(rightMap), rules,
        left_columns: left.columns, right_columns: right.columns,
      }
      const shouldUpdate = updateExisting && activeTemplateId
      const res = await fetch(`${API}/templates${shouldUpdate ? `/${activeTemplateId}` : ''}`, {
        method: shouldUpdate ? 'PUT' : 'POST', headers: { 'Content-Type':'application/json' }, body: JSON.stringify(payload)
      })
      const body = await res.json(); if (!res.ok) throw new Error(body.detail || 'Falha ao salvar template')
      setTemplateSelectionId(body.template_id); setActiveTemplateId(body.template_id); setTemplateName(body.name); setTemplateDescription(body.description || '')
      await loadTemplates()
    } catch (e) { setError(e instanceof Error ? e.message : 'Falha ao salvar template') } finally { setLoading(false) }
  }

  async function deleteTemplate() {
    if (!activeTemplateId) return
    setLoading(true); setError('')
    try {
      const res = await fetch(`${API}/templates/${activeTemplateId}`, { method:'DELETE' })
      if (!res.ok) { const body = await res.json(); throw new Error(body.detail || 'Falha ao excluir template') }
      setTemplateSelectionId(''); setActiveTemplateId(''); setTemplateName(''); setTemplateDescription(''); await loadTemplates()
    } catch (e) { setError(e instanceof Error ? e.message : 'Falha ao excluir template') } finally { setLoading(false) }
  }

  async function decide(pair: Pair, decision: 'approve'|'reject') {
    if (!result) return
    setLoading(true); setError('')
    try {
      const res = await fetch(`${API}/reconciliations/${result.summary.reconciliation_id}/pairs/${pair.pair_id}/decision`, {
        method: 'POST', headers: { 'Content-Type':'application/json' }, body: JSON.stringify({ decision })
      })
      const body = await res.json(); if (!res.ok) throw new Error(body.detail || 'Falha ao registrar decisão')
      setResult(body)
      setSelected(body.pairs.find((p: Pair)=>p.pair_id===pair.pair_id) || null)
    } catch (e) { setError(e instanceof Error ? e.message : 'Falha ao registrar decisão') } finally { setLoading(false) }
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return result?.pairs.filter(p => {
      const statusOk = filter === 'ALL' || p.status === filter
      const queryOk = !q || [p.document_left, p.document_right, p.description_left, p.description_right, p.match_cardinality].some(v => String(v || '').toLowerCase().includes(q))
      return statusOk && queryOk
    }) || []
  }, [result, filter, query])

  const goTo = (target: number) => {
    if (target === 1 || (target === 2 && left && right) || (target === 3 && left && right) || (target === 4 && result)) setStep(target)
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="side-brand"><div className="brand-mark"><ArrowLeftRight size={19}/></div><div><strong>Financial Reconciliation</strong><span>Intelligence</span></div></div>
      <nav className="side-nav">
        <SideItem icon={<Home/>} label="Início" active={step===1} onClick={()=>goTo(1)}/>
        <SideItem icon={<CheckCircle2/>} label="Conciliação" active={step===4} onClick={()=>result&&goTo(4)}/>
        <SideItem icon={<BookmarkPlus/>} label="Templates" active={step===2} onClick={()=>left&&right&&goTo(2)}/>
        <SideItem icon={<SlidersHorizontal/>} label="Regras" active={step===3} onClick={()=>goTo(3)}/>
        <SideItem icon={<Database/>} label="Bases de dados" active={false} onClick={()=>goTo(1)}/>
        <SideItem icon={<BarChart3/>} label="Relatórios" active={false} onClick={()=>result&&goTo(4)}/>
        <SideItem icon={<Settings/>} label="Configurações" active={false}/>
      </nav>
      <div className="sidebar-note"><BarChart3 size={26}/><b>Automatize<br/>a confiança financeira.</b><span>Regras determinísticas com revisão humana.</span></div>
    </aside>

    <div className="workspace">
      <header className="topbar">
        <div className="mobile-brand"><div className="brand-mark"><ArrowLeftRight size={18}/></div><div><strong>Financial Reconciliation</strong><span>Intelligence</span></div></div>
        <div className="top-spacer"/>
        <span className="engine-pill"><i/> Deterministic Engine</span>
        <button className="icon-btn" aria-label="Alternar tema" onClick={()=>setDark(v=>!v)}>{dark?<Sun size={17}/>:<Moon size={17}/>}</button>
        <button className="icon-btn notify" aria-label="Notificações"><Bell size={17}/></button>
        <div className="profile"><span>FO</span><div><b>Finance Operations</b><small>Workspace</small></div></div>
        <button className="mobile-menu" aria-label="Menu"><Menu size={20}/></button>
      </header>

      <main>
        <section className="hero">
          <div><span className="eyebrow">FINANCIAL OPERATIONS • MVP 0.3</span><h1>Concilie bases financeiras<br className="desktop-break"/> com regras claras e revisão humana.</h1><p>Suba duas planilhas, reutilize templates e deixe o motor encontrar matches 1:1, 1:N, N:1, divergências, duplicidades e exceções.</p></div>
          <div className="principle"><ShieldCheck size={18}/><span><b>Código concilia.</b><br/>Regras determinísticas primeiro; IA entra nas exceções depois.</span></div>
        </section>

        <nav className="steps">
          <StepButton number={1} title="Upload / Importação" subtitle="Envie as duas bases" current={step} onClick={()=>goTo(1)}/>
          <ChevronRight className="step-arrow" size={18}/>
          <StepButton number={2} title="Mapeamento" subtitle="Configure os campos" current={step} onClick={()=>goTo(2)}/>
          <ChevronRight className="step-arrow" size={18}/>
          <StepButton number={3} title="Regras e Templates" subtitle="Aplique critérios de conciliação" current={step} onClick={()=>goTo(3)}/>
          <ChevronRight className="step-arrow" size={18}/>
          <StepButton number={4} title="Resultado" subtitle="Analise e revise" current={step} onClick={()=>goTo(4)}/>
        </nav>

        {error && <div className="error"><CircleAlert size={18}/>{error}<button onClick={()=>setError('')}><X size={16}/></button></div>}

        {step === 1 && <section className="panel stage">
          <div className="section-head"><div><span className="eyebrow">01 • UPLOAD / IMPORTAÇÃO</span><h2>Envie as duas bases</h2><p>CSV ou XLSX, até 20 MB por arquivo.</p></div><Database size={24}/></div>
          <div className="upload-grid">
            <UploadCard title="Base principal" subtitle="Ex.: ERP, contas a receber, razão" dataset={left} onUpload={f=>upload(f,'left')}/>
            <UploadCard title="Base para comparação" subtitle="Ex.: extrato bancário, adquirente, parceiro" dataset={right} onUpload={f=>upload(f,'right')}/>
          </div>
          {left && right && <button className="primary stage-next" onClick={()=>setStep(2)}>Continuar para mapeamento <ArrowRight size={17}/></button>}
        </section>}

        {step === 2 && left && right && <section className="panel stage">
          <div className="section-head"><div><span className="eyebrow">02 • MAPEAMENTO</span><h2>Confirme as colunas</h2><p>O app sugere o mapeamento; você mantém o controle.</p></div><GitCompareArrows size={24}/></div>
          <div className="template-loader">
            <div><BookmarkPlus size={18}/><span><b>Template salvo</b><small>Reaplique mapeamento e regras de uma conciliação recorrente.</small></span></div>
            <select value={templateSelectionId} onChange={e=>setTemplateSelectionId(e.target.value)}>
              <option value="">Selecionar template</option>{templates.map(t=><option key={t.template_id} value={t.template_id}>{t.name}</option>)}
            </select>
            <button className="secondary" disabled={!templateSelectionId||loading} onClick={()=>applyTemplate(templateSelectionId)}>Aplicar</button>
          </div>
          <div className="mapping-grid">
            <MappingCard title={left.filename} ds={left} value={leftMap} onChange={setLeftMap}/>
            <div className="map-center"><GitCompareArrows/></div>
            <MappingCard title={right.filename} ds={right} value={rightMap} onChange={setRightMap}/>
          </div>
          <div className="footer-actions"><button className="secondary" onClick={()=>setStep(1)}>Voltar</button><button className="primary" disabled={!leftMap.amount||!rightMap.amount} onClick={()=>setStep(3)}>Definir regras <ArrowRight size={17}/></button></div>
        </section>}

        {step === 3 && <section className="panel stage">
          <div className="section-head"><div><span className="eyebrow">03 • REGRAS E TEMPLATES</span><h2>Regras da conciliação</h2><p>Tolerâncias são explícitas e auditáveis.</p></div><Settings2 size={24}/></div>
          <div className="rule-grid">
            <Rule label="Tolerância de valor" value={`R$ ${rules.amount_tolerance.toFixed(2).replace('.',',')}`}><input type="range" min="0" max="50" step="1" value={rules.amount_tolerance} onChange={e=>setRules({...rules,amount_tolerance:+e.target.value})}/></Rule>
            <Rule label="Tolerância de data" value={`${rules.date_tolerance_days} dia(s)`}><input type="range" min="0" max="7" value={rules.date_tolerance_days} onChange={e=>setRules({...rules,date_tolerance_days:+e.target.value})}/></Rule>
            <Rule label="Similaridade mínima" value={`${Math.round(rules.description_similarity*100)}%`}><input type="range" min="50" max="100" value={rules.description_similarity*100} onChange={e=>setRules({...rules,description_similarity:+e.target.value/100})}/></Rule>
            <Rule label="Auto aprovação" value={`${Math.round(rules.auto_approve_threshold*100)}%`}><input type="range" min="75" max="100" value={rules.auto_approve_threshold*100} onChange={e=>setRules({...rules,auto_approve_threshold:+e.target.value/100})}/></Rule>
          </div>
          <div className="rule-options">
            <label className="check-row"><input type="checkbox" checked={rules.require_document_exact} onChange={e=>setRules({...rules,require_document_exact:e.target.checked})}/><span><b>Exigir documento exato quando disponível</b><small>Bloqueia matches quando identificadores não coincidem.</small></span></label>
            <label className="check-row"><input type="checkbox" checked={rules.group_matching_enabled} onChange={e=>setRules({...rules,group_matching_enabled:e.target.checked})}/><span><b>Ativar matching agrupado 1:N / N:1</b><small>Combina lançamentos fracionados ou pagamentos agrupados sem reutilizar registros.</small></span></label>
          </div>
          {rules.group_matching_enabled && <div className="rule-grid compact-rules">
            <Rule label="Máximo por agrupamento" value={`${rules.max_group_size} registros`}><input type="range" min="2" max="5" step="1" value={rules.max_group_size} onChange={e=>setRules({...rules,max_group_size:+e.target.value})}/></Rule>
            <Rule label="Confiança mínima do grupo" value={`${Math.round(rules.group_match_threshold*100)}%`}><input type="range" min="70" max="100" value={rules.group_match_threshold*100} onChange={e=>setRules({...rules,group_match_threshold:+e.target.value/100})}/></Rule>
          </div>}
          <div className="template-save">
            <div className="template-save-copy"><BookmarkPlus size={19}/><span><b>Salvar configuração como template</b><small>Guarde colunas, tolerâncias e regras para o próximo período.</small></span></div>
            <div className="template-fields"><input value={templateName} onChange={e=>setTemplateName(e.target.value)} placeholder="Ex.: ERP × Itaú"/><input value={templateDescription} onChange={e=>setTemplateDescription(e.target.value)} placeholder="Descrição opcional"/></div>
            <div className="template-actions"><button className="secondary" disabled={loading||!templateName.trim()} onClick={()=>saveTemplate(false)}><BookmarkPlus size={15}/> Salvar novo</button>{activeTemplateId&&<><button className="secondary" disabled={loading} onClick={()=>saveTemplate(true)}>Atualizar</button><button className="icon-btn danger" disabled={loading} onClick={deleteTemplate} title="Excluir template"><Trash2 size={16}/></button></>}</div>
          </div>
          <div className="footer-actions"><button className="secondary" onClick={()=>setStep(2)}>Voltar</button><button className="primary" disabled={loading} onClick={run}>{loading?<RefreshCw className="spin" size={17}/>:<GitCompareArrows size={17}/>} Executar conciliação</button></div>
        </section>}

        {step === 4 && result && <section className="results-stage panel">
          <div className="result-head"><div><span className="eyebrow">CONCILIAÇÃO • {result.summary.reconciliation_id}</span><h2>Resultado da conciliação</h2><p>{result.summary.total_left.toLocaleString('pt-BR')} registros na base principal • taxa de match {(result.summary.match_rate*100).toFixed(1)}% • {result.summary.duplicates.toLocaleString('pt-BR')} duplicado(s)</p></div><div className="result-actions"><span className="processed">Processado agora</span><button className="icon-btn"><MoreHorizontal size={17}/></button><a className="primary export" href={`${API}/reconciliations/${result.summary.reconciliation_id}/export.csv`}><Download size={16}/> Exportar CSV</a></div></div>
          <div className="kpi-grid">
            <Kpi icon={<CheckCircle2/>} label="Conciliados" value={result.summary.matched} percent={result.summary.total_left?result.summary.matched/result.summary.total_left:0} tone="good"/>
            <Kpi icon={<Layers3/>} label="Agrupados" value={result.summary.grouped_matches} percent={result.summary.total_left?result.summary.grouped_matches/result.summary.total_left:0} tone="group"/>
            <Kpi icon={<CircleAlert/>} label="Prováveis" value={result.summary.probable_matches} percent={result.summary.total_left?result.summary.probable_matches/result.summary.total_left:0} tone="warn"/>
            <Kpi icon={<FileWarning/>} label="Divergências" value={result.summary.divergences} percent={result.summary.total_left?result.summary.divergences/result.summary.total_left:0} tone="bad"/>
            <Kpi icon={<CircleX/>} label="Não encontrados" value={result.summary.unmatched} percent={result.summary.total_left?result.summary.unmatched/result.summary.total_left:0} tone="neutral"/>
          </div>
          <div className="balance-strip"><div><span>Base principal</span><b>{money(result.summary.total_amount_left)}</b></div><ArrowRight size={20}/><div><span>Base comparada</span><b>{money(result.summary.total_amount_right)}</b></div><div className="net"><span>Diferença líquida</span><b>{money(result.summary.net_difference)}</b></div></div>
          <div className="table-panel">
            <div className="table-toolbar"><div className="filters">{['ALL','MATCH','PROBABLE_MATCH','DIVERGENCE','UNMATCHED'].map(f=><button key={f} onClick={()=>setFilter(f)} className={filter===f?'active':''}>{f==='ALL'?'Todos':statusLabel(f)}</button>)}</div><label className="table-search"><Search size={15}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Buscar por documento, valor ou descrição..."/></label><button className="filter-icon"><SlidersHorizontal size={15}/></button></div>
            <div className="table-wrap"><table><thead><tr><th>Status</th><th>Tipo</th><th>Documento</th><th>Descrição</th><th>Valor A</th><th>Valor B</th><th>Diferença</th><th>Confiança</th><th>Ações</th></tr></thead><tbody>{filtered.map(p=><tr key={p.pair_id} onClick={()=>setSelected(p)}><td><span className={`status s-${p.status.toLowerCase()}`}>{statusLabel(p.status)}</span></td><td><span className="cardinality">{p.match_cardinality}</span></td><td>{p.document_left||p.document_right||'—'}</td><td className="description-cell">{p.description_left||p.description_right||'—'}</td><td>{p.amount_left!=null?money(p.amount_left):'—'}</td><td>{p.amount_right!=null?money(p.amount_right):'—'}</td><td className={(p.amount_difference||0)!==0?'negative':''}>{p.amount_difference!=null?money(p.amount_difference):'—'}</td><td><ConfidenceBar value={p.confidence}/></td><td><MoreHorizontal size={16}/></td></tr>)}</tbody></table></div>
          </div>
          <div className="result-footer"><span>Mostrando {filtered.length.toLocaleString('pt-BR')} registro(s)</span><button className="secondary new-run" onClick={()=>{setResult(null);setStep(1)}}><RefreshCw size={15}/> Nova conciliação</button></div>
        </section>}

        <div className="enterprise-footer">
          <Feature icon={<Upload/>} title="Upload / Importação" subtitle="CSV, XLSX e integração via API."/>
          <Feature icon={<Layers3/>} title="Mapeamento" subtitle="Relacione campos entre as bases."/>
          <Feature icon={<Settings2/>} title="Regras e Templates" subtitle="Regras determinísticas e exceções."/>
          <Feature icon={<BarChart3/>} title="Resultados" subtitle="KPIs, confiança e revisão humana."/>
        </div>
      </main>

      <nav className="mobile-bottom-nav">
        <button className={step===1?'active':''} onClick={()=>goTo(1)}><Home size={18}/><span>Início</span></button>
        <button className={step===1?'active-secondary':''} onClick={()=>goTo(1)}><Upload size={18}/><span>Upload</span></button>
        <button className={step===3?'active':''} onClick={()=>goTo(3)}><Settings2 size={18}/><span>Regras</span></button>
        <button className={step===4?'active':''} onClick={()=>result&&goTo(4)}><BarChart3 size={18}/><span>Resultado</span></button>
      </nav>
    </div>

    {selected && <div className="drawer-backdrop" onClick={()=>setSelected(null)}><aside className="drawer" onClick={e=>e.stopPropagation()}><button className="drawer-close" onClick={()=>setSelected(null)}><X/></button><div className="drawer-badges"><span className={`status s-${selected.status.toLowerCase()}`}>{statusLabel(selected.status)}</span><span className="cardinality">{selected.match_cardinality}</span></div><h3>Detalhes da correspondência</h3><div className="confidence"><span>Confiança</span><b>{Math.round(selected.confidence*100)}%</b></div><div className="compare-two"><GroupEntry title="Base principal" rows={selected.left_rows} fallback={<Entry title="Base principal" p={selected} side="left"/>}/><GroupEntry title="Base comparada" rows={selected.right_rows} fallback={<Entry title="Base comparada" p={selected} side="right"/>}/></div><div className="reason-box"><b>Por que o motor classificou assim?</b>{selected.reasons.map(r=><span key={r}>{r}</span>)}</div>{['PROBABLE_MATCH','DIVERGENCE','UNMATCHED'].includes(selected.status)&&<div className="decision-actions"><button className="secondary reject" disabled={loading} onClick={()=>decide(selected,'reject')}><X size={16}/> Manter exceção</button><button className="primary" disabled={loading} onClick={()=>decide(selected,'approve')}><Check size={16}/> Aprovar match</button></div>}</aside></div>}
  </div>
}

function SideItem({icon,label,active,onClick}:{icon:React.ReactNode;label:string;active:boolean;onClick?:()=>void}) { return <button className={active?'active':''} onClick={onClick}><span>{icon}</span>{label}</button> }
function StepButton({number,title,subtitle,current,onClick}:{number:number;title:string;subtitle:string;current:number;onClick:()=>void}) { const done=current>number; return <button className={current===number?'active':done?'done':''} onClick={onClick}><span className="step-number">{done?<Check size={14}/>:number}</span><span className="step-copy"><b>{title}</b><small>{subtitle}</small></span></button> }
function Feature({icon,title,subtitle}:{icon:React.ReactNode;title:string;subtitle:string}) { return <div className="feature"><span>{icon}</span><div><b>{title}</b><small>{subtitle}</small></div></div> }
function normMap(m: Mapping) { return { amount:m.amount, date:m.date||null, description:m.description||null, document:m.document||null } }
function fromApiMap(m: Template['left_mapping']): Mapping { return { amount:m.amount, date:m.date||'', description:m.description||'', document:m.document||'' } }
function MappingCard({title,ds,value,onChange}:{title:string;ds:Dataset;value:Mapping;onChange:(m:Mapping)=>void}) { return <div className="mapping-card"><div className="file-head"><FileSpreadsheet size={18}/><strong>{title}</strong></div>{([['amount','Valor *'],['date','Data'],['description','Descrição'],['document','Documento']] as [keyof Mapping,string][]).map(([key,label])=><label key={key}><span>{label}</span><select value={value[key]} onChange={e=>onChange({...value,[key]:e.target.value})}><option value="">Não mapear</option>{ds.columns.map(c=><option key={c}>{c}</option>)}</select></label>)}</div> }
function Rule({label,value,children}:{label:string;value:string;children:React.ReactNode}) { return <div className="rule"><div><b>{label}</b><span>{value}</span></div>{children}</div> }
function Kpi({icon,label,value,percent,tone}:{icon:React.ReactNode;label:string;value:number;percent:number;tone:string}) { return <div className={`kpi ${tone}`}><div className="kpi-icon">{icon}</div><div><span>{label}</span><b>{value.toLocaleString('pt-BR')}</b><small>{(percent*100).toFixed(1)}% do total</small></div></div> }
function ConfidenceBar({value}:{value:number}) { const pct=Math.round(value*100); return <div className="confidence-cell"><div><i style={{width:`${pct}%`}}/></div><b>{pct}%</b></div> }
function Entry({title,p,side}:{title:string;p:Pair;side:'left'|'right'}) { const v=(name:string)=>(p as unknown as Record<string,unknown>)[`${name}_${side}`]; return <div className="entry"><b>{title}</b><dl><dt>Documento</dt><dd>{String(v('document')||'—')}</dd><dt>Valor</dt><dd>{typeof v('amount')==='number'?money(v('amount') as number):'—'}</dd><dt>Data</dt><dd>{String(v('date')||'—')}</dd><dt>Descrição</dt><dd>{String(v('description')||'—')}</dd></dl></div> }
function GroupEntry({title,rows,fallback}:{title:string;rows:Record<string,unknown>[];fallback:React.ReactNode}) {
  if (!rows || rows.length <= 1) return <>{fallback}</>
  return <div className="entry group-entry"><b>{title} • {rows.length} registros</b><div className="group-row-list">{rows.map((row,index)=><div className="group-row" key={index}><span>#{index+1}</span><code>{Object.entries(row).slice(0,4).map(([key,value])=>`${key}: ${String(value)}`).join(' • ')}</code></div>)}</div></div>
}

createRoot(document.getElementById('root')!).render(<App />)
