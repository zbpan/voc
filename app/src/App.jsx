import React, { useEffect, useMemo, useState } from 'react'
import { ArrowDownToLine, ArrowRight, AudioLines, Building2, ChevronLeft, ChevronRight, CircleHelp, ClipboardCheck, FileAudio, FileText, Globe2, Headphones, LayoutDashboard, ListFilter, Menu, MessageSquareText, Plus, Search, Settings2, SlidersHorizontal, Upload, X } from 'lucide-react'
import { api, Badge, count, dateTime, Empty, ErrorBox, label, Loading, Modal, time, Toast, useData } from './shared.jsx'
import { Collection, Intake } from './Intake.jsx'
import { EvidenceDrawer, ReportDetail } from './Evidence.jsx'
import { Executive } from './Executive.jsx'
import { ModelSettings } from './ModelSettings.jsx'

const nav = [
  ['executive', LayoutDashboard, '经营总览', '看清集团体验变化，把资源投入最值得改善的地方。'],
  ['dashboard', LayoutDashboard, '洞察总览', '从客户原声中，找到值得行动的问题。'],
  ['records', AudioLines, '原声收件箱', '每一条反馈，都有可回溯的原始证据。'],
  ['events', ClipboardCheck, '体验事件', '复核客户诉求，让发现进入跟进流程。'],
  ['reports', FileText, '洞察报告', '把分散的客户声音，整理成有依据的行动建议。'],
  ['stores', Building2, '门店与采集', '为每个服务现场，建立独立的反馈入口。'],
  ['settings', Settings2, '工作空间', '管理工作空间，查看模型和运行状态。'],
  ['model', SlidersHorizontal, '模型配置', '连接你的模型服务，让配置与数据留在本机。'],
]

function Trend({ data }) {
  const [narrow, setNarrow] = useState(window.innerWidth <= 700)
  useEffect(() => {
    const media = window.matchMedia('(max-width:700px)')
    const update = () => setNarrow(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  if (data.length === 1) return <div className="trend-single"><span>{data[0].date} · 已接收</span><div><strong>{data[0].total}</strong><span>条反馈</span><small>其中 {data[0].negative} 条负向或褒贬并存</small></div><p>当前只有一天数据，继续采集后可观察每日变化。</p></div>
  const max = Math.max(1, ...data.map(d => d.total))
  const width = narrow ? 340 : 700, height = 160, bottom = 137, top = 10
  const x = i => 30 + i * (width - 46) / Math.max(1, data.length - 1)
  const y = n => bottom - n / max * (bottom - top)
  const path = key => data.map((d, i) => `${i ? 'L' : 'M'}${x(i)},${y(d[key])}`).join(' ')
  return <div className="trend-chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`每日反馈数量趋势，共${data.reduce((n, d) => n + d.total, 0)}条`}>{[0, .5, 1].map(v => <g key={v}><line x1="30" x2={width - 16} y1={y(max * v)} y2={y(max * v)} stroke="#e8edea" strokeDasharray="3 5" /><text x="0" y={y(max * v) + 4} className="axis-text">{Number((max * v).toFixed(1))}</text></g>)}<path d={path('total')} fill="none" stroke="#287b65" strokeWidth="2.5" strokeLinejoin="round" /><path d={path('negative')} fill="none" stroke="#b48151" strokeWidth="1.8" strokeDasharray="4 4" />{data.map((d, i) => <g key={d.date}><circle cx={x(i)} cy={y(d.total)} r={d.total ? 3.8 : 1.5} fill="#287b65"><title>{d.date}：{d.total}条反馈，{d.negative}条负向或褒贬并存</title></circle>{[0, Math.floor((data.length - 1) / 2), data.length - 1].includes(i) && <text x={x(i)} y="158" textAnchor={i === 0 ? 'start' : i === data.length - 1 ? 'end' : 'middle'} className="axis-text">{d.date.slice(5)}</text>}</g>)}</svg></div>
}

function RecordTable({ items, open, compact = false }) {
  const media = r => r.metadata?.modalities?.map(m => ({ text: '文字', audio: '语音', image: '图片' })[m]).join('＋') || label(r.media_type)
  return <div className="table-scroll"><table className="record-table"><thead><tr><th>原始反馈</th><th>门店 / 来源</th>{!compact && <th>情绪 / 事件</th>}<th>处理状态</th><th className="align-right">接收时间</th></tr></thead><tbody>{items.map(r => <tr key={r.id}><td><button className="record-link" onClick={() => open(r.id)}><span className={`file-symbol ${r.media_type === 'text' ? 'text' : ''}`}>{r.media_type === 'audio' || r.metadata?.modalities?.includes('audio') ? <FileAudio size={19} /> : <MessageSquareText size={19} />}</span><span><strong>{r.title}</strong><small>{media(r)}{r.duration > 0 ? ` ${time(r.duration)}` : ''} · {label(r.language || r.language_hint).replace('auto', '自动识别')}{r.summary && ` · ${r.summary}`}</small></span></button></td><td><span>{r.store_name || '未分配'}</span><small>{label(r.source_type)}</small></td>{!compact && <td>{r.status === 'completed' ? <><Badge value={r.sentiment} /><small>{r.is_feedback ? `${r.event_count} 个事件` : '非体验反馈'}</small></> : <span className="muted">—</span>}</td>}<td><Badge value={r.status} />{r.status === 'processing' && <small>{r.stage}</small>}{r.status === 'failed' && <button className="text-button tiny" onClick={() => open(r.id)}>查看原因</button>}</td><td className="align-right muted tiny">{dateTime(r.created_at)}</td></tr>)}</tbody></table></div>
}

function Pager({ total, offset, setOffset }) { return total > 50 ? <div className="pagination"><span className="muted">第{offset + 1}–{Math.min(total, offset + 50)}条，共{total}条</span><button className="icon-button" aria-label="上一页" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}><ChevronLeft size={18} /></button><button className="icon-button" aria-label="下一页" disabled={offset + 50 >= total} onClick={() => setOffset(offset + 50)}><ChevronRight size={18} /></button></div> : null }

function Dashboard({ query, revision, open, intake, changePage }) {
  const { data: stats, error, loading } = useData(`/api/dashboard?${query}`, revision, 5000)
  const { data: records } = useData(`/api/records?${query}&limit=5`, revision, 5000)
  const { data: events } = useData(`/api/events?${query}&limit=4`, revision, 5000)
  if (!stats) return error ? <ErrorBox error={error} /> : <Loading />
  return <><ErrorBox error={error} /><section className="metric-strip">
    {[['已接收反馈', count(stats.records), `${stats.completed} 条已完成分析`, AudioLines], ['负向反馈占比', stats.negative_percent == null ? '—' : `${stats.negative_percent}%`, `基于 ${stats.feedback_records} 条有效体验反馈`, MessageSquareText], ['高严重度待跟进', count(stats.high_open), '高 / 紧急 · 尚未解决', ListFilter], ['待人工复核', count(stats.pending_review), `${stats.resolved} 个事件已解决`, ClipboardCheck]].map(([name, value, note, Icon], i) => <div className={`metric metric-${i}`} key={name}><div className="row spread"><span>{name}</span><Icon size={17} /></div><strong>{value}</strong><small>{note}</small></div>)}
  </section>
  {!stats.records ? <section className="welcome-panel"><div className="welcome-copy"><span className="eyebrow">从第一条真实反馈开始</span><h2>把客户的声音，<br />带进每一次改进。</h2><p>导入录音或文字，了解客户的真实体验。<br />配置的模型将整理原文、主题与可回听的证据。</p><button className="button primary" onClick={intake}><Plus size={17} />添加第一条反馈</button></div><div className="welcome-steps">{[['01', '收集原声', '上传客服录音、接收语音留言或文字反馈。', AudioLines], ['02', '核对证据', '按主题和严重度找到问题，回听并确认。', Headphones], ['03', '推进改进', '记录负责人和跟进结果，生成洞察报告。', ClipboardCheck]].map(([n, title, detail, Icon]) => <div key={n}><span className="step-num">{n}</span><span><strong>{title}</strong><p>{detail}</p></span><Icon size={21} /></div>)}</div></section> : <>
    {(stats.queued > 0 || stats.failed > 0) && <div className="queue-banner"><AudioLines size={17} /><span>{stats.queued > 0 && `${stats.queued} 条反馈正在队列中处理`}{stats.queued > 0 && stats.failed > 0 && ' · '}{stats.failed > 0 && `${stats.failed} 条处理失败，可查看原因后重试`}</span><button className="text-button" onClick={() => changePage('records')}>查看收件箱<ArrowRight size={15} /></button></div>}
    <div className="dashboard-grid"><section className="panel trend-panel"><div className="panel-head"><div><h2>客户声音趋势</h2><span className="tiny muted">按接收日期（UTC）统计 · 最长展示90天</span></div><div className="chart-legend"><span><i />全部反馈</span><span><i />负向 / 褒贬并存</span></div></div><Trend data={stats.trend} /></section><section className="panel themes-panel"><div className="panel-head"><h2>体验主题</h2><span className="tiny muted">{stats.events} 个有效事件</span></div>{stats.themes.length ? <div className="theme-list">{stats.themes.slice(0, 5).map(t => <div key={t.name}><div className="row spread"><span>{t.name}</span><strong>{t.count}</strong></div><div className="bar-track"><span style={{ width: `${t.count / Math.max(...stats.themes.map(t => t.count)) * 100}%` }} /></div></div>)}</div> : <Empty title="等待体验事件" detail="分析完成后将在这里汇总主题" />}</section></div>
    {events?.items.length > 0 && <section className="attention-strip"><div className="attention-heading"><span className="eyebrow">关注清单</span><h2>值得进一步了解</h2><button className="text-button" onClick={() => changePage('events')}>全部事件<ArrowRight size={15} /></button></div><div className="attention-list">{events.items.slice(0, 3).map(e => <button className="attention-item" key={e.id} onClick={() => open(e.record_id)}><div className="row spread"><span className="tiny muted">{e.theme}</span><Badge value={e.severity}>{label(e.severity)}严重度</Badge></div><h3>{e.title}</h3><p>“{e.quote}”</p><span className="tiny muted">{e.store_name || '未分配门店'} · {label(e.review_status)}</span></button>)}</div></section>}
  </>}
  <section className="panel inbox-preview"><div className="panel-head"><h2>最近收到的原声 <span className="muted tiny">{stats.records ? count(stats.records) : ''}</span></h2><button className="text-button" onClick={() => changePage('records')}>打开收件箱<ArrowRight size={15} /></button></div>{records?.items.length ? <RecordTable items={records.items} open={open} compact /> : <div className="empty-inline"><Headphones size={20} /><span>还没有反馈。每一条新声音，都会从这里开始。</span></div>}</section><div className="data-footnote">负向占比含“负向”和“褒贬并存”，分母为已完成且包含体验反馈的记录；事件统计默认排除已排除事件。</div>
  </>
}

function Records({ query, revision, open, intake }) {
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  useEffect(() => setOffset(0), [query, status])
  const { data, error, loading } = useData(`/api/records?${query}&status=${status}&offset=${offset}`, revision, 5000)
  return <section className="panel"><div className="panel-head"><div className="tabs inline-tabs">{[['', '全部反馈'], ['queued', '排队中'], ['processing', '分析中'], ['completed', '已完成'], ['failed', '失败']].map(([v, t]) => <button key={v} className={status === v ? 'active' : ''} onClick={() => setStatus(v)}>{t}</button>)}</div><span className="tiny muted">{data?.total ?? '—'} 条</span></div><ErrorBox error={error} />{loading && !data ? <Loading /> : data?.items.length ? <RecordTable items={data.items} open={open} /> : <Empty icon={Headphones} title="当前范围没有反馈" detail="试试调整筛选条件，或添加一条新的客户反馈。" action={<button className="button small" onClick={intake}><Plus size={15} />添加反馈</button>} />}<Pager total={data?.total || 0} offset={offset} setOffset={setOffset} /></section>
}

function Events({ query, revision, open, themes }) {
  const [filters, setFilters] = useState({ theme: '', severity: '', review_status: '', workflow_status: '' })
  const [offset, setOffset] = useState(0)
  useEffect(() => setOffset(0), [query, filters])
  const eventQuery = new URLSearchParams(filters).toString()
  const { data, error, loading } = useData(`/api/events?${query}&${eventQuery}&offset=${offset}`, revision, 5000)
  return <><div className="event-filter-bar"><SlidersHorizontal size={17} /><select aria-label="事件主题" value={filters.theme} onChange={e => setFilters(f => ({ ...f, theme: e.target.value }))}><option value="">全部主题</option>{themes.map(t => <option key={t}>{t}</option>)}</select>{[['severity', '全部严重度', ['low', 'medium', 'high', 'critical']], ['review_status', '有效事件（含待复核）', ['pending', 'confirmed', 'dismissed']], ['workflow_status', '全部跟进状态', ['new', 'in_progress', 'resolved']]].map(([key, name, values]) => <select key={key} aria-label={name} value={filters[key]} onChange={e => setFilters(f => ({ ...f, [key]: e.target.value }))}><option value="">{name}</option>{values.map(v => <option key={v} value={v}>{label(v)}</option>)}</select>)}</div><section className="panel"><div className="panel-head"><h2>体验事件 <span className="tiny muted">{data?.total || 0}</span></h2><span className="tiny muted">点击查看原声与跟进</span></div><ErrorBox error={error} />{loading && !data ? <Loading /> : data?.items.length ? <div className="event-table">{data.items.map(e => <button className="event-row" key={e.id} onClick={() => open(e.record_id)}><span className={`severity-line ${e.severity}`} /><div className="event-row-content"><div className="row wrap"><h3>{e.title}</h3><Badge value={e.severity}>{label(e.severity)}严重度</Badge><Badge value={e.review_status} /></div><p dir="auto">“{e.quote}”</p><span className="tiny muted">{e.store_name || '未分配门店'} · {e.theme} · {label(e.language)} · {dateTime(e.created_at)}</span></div><div className="event-row-state"><Badge value={e.workflow_status} /><small>{e.owner || '未分配跟进人'}</small></div><ChevronRight size={17} /></button>)}</div> : <Empty icon={ClipboardCheck} title="暂无符合条件的体验事件" detail="完成录音分析后，可在这里确认主题、严重度和跟进状态。" />}<Pager total={data?.total || 0} offset={offset} setOffset={setOffset} /></section></>
}

function Reports({ workspace, scope, revision, open, changed }) {
  const { data, error, loading } = useData(`/api/reports?workspace_id=${workspace}`, revision, 5000)
  const [title, setTitle] = useState('客户原声洞察报告')
  const [create, setCreate] = useState(false)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  async function submit(e) {
    e.preventDefault(); setBusy(true); setActionError('')
    try { const report = await api('/api/reports', { method: 'POST', body: JSON.stringify({ title, scope }) }); setCreate(false); changed('报告已进入生成队列'); open(report.id) } catch (e) { setActionError(e.message) } finally { setBusy(false) }
  }
  return <><div className="report-intro"><div><span className="eyebrow">从证据到行动</span><h2>给每一个建议，找到依据。</h2><p>按当前门店、日期与搜索范围生成报告，保留统计快照和原声引用。</p></div><button className="button primary" onClick={() => { setCreate(true); setActionError('') }}><Plus size={17} />生成洞察报告</button></div><section className="panel"><div className="panel-head"><h2>工作空间报告</h2><span className="tiny muted">{data?.length || 0} 份</span></div><ErrorBox error={error} />{loading && !data ? <Loading /> : data?.length ? <div className="report-list">{data.map(r => <button key={r.id} onClick={() => open(r.id)} className="report-list-item"><span className="report-icon"><FileText size={24} /></span><div><h3>{r.title}</h3><p>{dateTime(r.created_at)} · {r.model}</p></div><Badge value={r.status} /><ChevronRight size={18} /></button>)}</div> : <Empty icon={FileText} title="第一份洞察，从真实反馈开始" detail="至少有一条有效事件后，即可生成带原声引用的报告。" />}</section>{create && <Modal title="生成洞察报告" close={() => !busy && setCreate(false)}><form className="modal-body" onSubmit={submit}><label>报告名称<input required maxLength={160} value={title} onChange={e => setTitle(e.target.value)} /></label><p className="field-note">采用页面顶部的门店、日期和搜索范围。引用有效事件，最多200条，按严重度优先；报告保留生成时快照。</p><ErrorBox error={actionError} /><div className="modal-foot"><span className="muted">使用当前配置的模型</span><button className="button primary" disabled={busy}>{busy ? '提交中…' : '开始生成'}<ArrowRight size={16} /></button></div></form></Modal>}</>
}

function Stores({ stores, workspace, changed }) {
  const [add, setAdd] = useState(false)
  const [qr, setQr] = useState(null)
  const [name, setName] = useState('')
  const [region, setRegion] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e) { e.preventDefault(); setBusy(true); setError(''); try { await api('/api/stores', { method: 'POST', body: JSON.stringify({ workspace_id: workspace, name, region }) }); setAdd(false); setName(''); setRegion(''); changed('门店已创建') } catch (e) { setError(e.message) } finally { setBusy(false) } }
  return <><div className="section-toolbar"><span className="muted">{stores.length} 家门店 · 独立反馈入口</span><button className="button primary" onClick={() => { setAdd(true); setError('') }}><Plus size={17} />新建门店</button></div><div className="store-grid">{stores.map(s => <article className="store-card" key={s.id}><div className="store-top"><span className="store-icon"><Building2 size={25} /></span><span className="tiny muted">{s.region || '未设置区域'}</span></div><h2>{s.name}</h2><p><strong>{s.record_count}</strong> 条已接收反馈</p><div className="store-actions"><a className="text-button" href={`/collect/${s.collection_token}`} target="_blank" rel="noreferrer">打开采集页<ArrowRight size={15} /></a><button className="button small" onClick={() => setQr(s)}>链接与二维码</button></div></article>)}</div>{!stores.length && <section className="panel"><Empty icon={Building2} title="建立您的第一家门店" detail="新建后即可获得专属语音与文字反馈采集入口。" /></section>}<div className="local-note"><CircleHelp size={16} /><span>当前为本机运行。采集页可在本机体验；手机跨设备使用需部署到可访问的HTTPS地址。</span></div>{add && <Modal title="新建门店" close={() => !busy && setAdd(false)}><form className="modal-body" onSubmit={submit}><label>门店名称<input required maxLength={80} value={name} onChange={e => setName(e.target.value)} placeholder="例如：滨江店" /></label><label>区域<input maxLength={80} value={region} onChange={e => setRegion(e.target.value)} placeholder="例如：新加坡 · 中区" /></label><ErrorBox error={error} /><div className="modal-foot"><span /><button className="button primary" disabled={busy || !name.trim()}>创建门店</button></div></form></Modal>}{qr && <Modal title={qr.name} close={() => setQr(null)}><div className="modal-body qr-body"><img src={`/api/collect/${qr.collection_token}/qr`} alt={`${qr.name}的反馈采集二维码`} width="220" height="220" /><p>语音留言 · 文字反馈 · 自动归属门店</p><input aria-label="采集链接" readOnly value={`${location.origin}/collect/${qr.collection_token}`} onFocus={e => e.target.select()} /><button className="button primary" onClick={async () => { try { await navigator.clipboard.writeText(`${location.origin}/collect/${qr.collection_token}`); changed('采集链接已复制') } catch { changed('请选中上方链接手动复制') } }}>复制链接</button><p className="field-note">此链接指向本机地址，当前二维码不能跨设备访问。</p></div></Modal>}</>
}

function Workspace({ workspace, workspaces, health, changed, select }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(e) { e.preventDefault(); setBusy(true); setError(''); try { const w = await api('/api/workspaces', { method: 'POST', body: JSON.stringify({ name }) }); setName(''); changed('工作空间已创建'); select(w.id) } catch (e) { setError(e.message) } finally { setBusy(false) } }
  return <div className="settings-grid"><section className="panel settings-panel"><div className="eyebrow">运行环境</div><h2>当前运行状态</h2><dl><dt>当前空间</dt><dd>{workspaces.find(w => w.id === workspace)?.name}</dd><dt>分析模型</dt><dd>{health?.model || '读取中'}</dd><dt>服务地域</dt><dd>{health?.region || '—'}</dd><dt>API 凭据</dt><dd><Badge value={health?.configured ? 'completed' : 'failed'}>{health?.configured ? '后端已配置' : '尚未配置'}</Badge></dd><dt>音频处理</dt><dd>{health?.ffmpeg ? 'FFmpeg 可用' : 'FFmpeg 未检测到'}</dd><dt>数据存储</dt><dd>本机 SQLite + 原始音频文件</dd><dt>访问方式</dt><dd>本机模式 · 127.0.0.1</dd></dl><p className="field-note">可在模型配置页设置服务地址、模型和密钥，也可使用环境变量。工作空间用于整理数据，首版本机模式未设置账号登录。</p></section><section className="panel settings-panel"><div className="eyebrow">独立整理项目</div><h2>新建工作空间</h2><p className="muted">按品牌、项目或测试用途组织门店与反馈。</p><form onSubmit={submit}><label>空间名称<input required value={name} maxLength={80} onChange={e => setName(e.target.value)} placeholder="例如：酒店体验项目" /></label><ErrorBox error={error} /><button className="button primary" disabled={busy || !name.trim()}><Plus size={17} />创建工作空间</button></form><div className="settings-about"><h3>首版工作流程</h3><p>采集与上传 → 模型分析 → 人工复核。确认后的事件可记录负责人和处理进展，报告保留生成时的数据快照。</p></div></section></div>
}

export default function App() {
  const token = location.pathname.match(/^\/collect\/([^/]+)\/?$/)?.[1]
  return token ? <Collection token={token} /> : <Workbench />
}

function Workbench() {
  const [page, setPage] = useState('executive')
  const [workspace, setWorkspace] = useState(() => new URLSearchParams(location.search).get('workspace') || localStorage.getItem('voc-workspace') || 'default')
  const [store, setStore] = useState('')
  const [range, setRange] = useState('all')
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [revision, setRevision] = useState(0)
  const [intake, setIntake] = useState(false)
  const [record, setRecord] = useState(null)
  const [report, setReport] = useState(null)
  const [toast, setToast] = useState('')
  const [mobileNav, setMobileNav] = useState(false)
  const { data: health, error: healthError } = useData('/api/health', revision)
  const { data: workspaces, error: workspaceError } = useData('/api/workspaces', revision)
  const { data: stores, error: storeError } = useData(`/api/stores?workspace_id=${workspace}`, revision)
  useEffect(() => { const timer = setTimeout(() => setDebounced(search), 300); return () => clearTimeout(timer) }, [search])
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(''), 4000); return () => clearTimeout(timer) }, [toast])
  useEffect(() => { if (workspaces?.length && !workspaces.some(w => w.id === workspace)) selectWorkspace('default') }, [workspaces])
  function changed(message) { setRevision(r => r + 1); if (message) setToast(message) }
  function selectWorkspace(id) { setWorkspace(id); localStorage.setItem('voc-workspace', id); history.replaceState(null, '', `/?workspace=${encodeURIComponent(id)}`); setStore(''); setSearch(''); setDebounced(''); setRecord(null); setReport(null); setIntake(false) }
  const scope = useMemo(() => { const result = { workspace_id: workspace }; if (store) result.store_id = store; if (debounced) result.search = debounced; if (page !== 'executive' && range !== 'all') { const d = new Date(); d.setUTCDate(d.getUTCDate() - Number(range) + 1); result.start = d.toISOString().slice(0, 10) } return result }, [workspace, store, range, debounced, page])
  const query = new URLSearchParams(scope).toString()
  const meta = nav.find(n => n[0] === page)
  function changePage(next) { setPage(next); setMobileNav(false) }
  return <div className="app-shell">{mobileNav && <button className="nav-scrim" aria-label="关闭导航" onClick={() => setMobileNav(false)} />}<aside className={`sidebar ${mobileNav ? 'mobile-open' : ''}`}><a className="brand" href="/" onClick={e => { e.preventDefault(); changePage('executive') }}><span className="brand-mark"><AudioLines size={22} aria-hidden="true" /></span><span>VOC <small>客户原声工作台</small></span></a><div className="workspace-switch"><span>当前工作空间</span><select aria-label="当前工作空间" value={workspace} onChange={e => selectWorkspace(e.target.value)}>{(workspaces || [{ id: workspace, name: '加载中…' }]).map(w => <option value={w.id} key={w.id}>{w.name}</option>)}</select></div><div className="nav-caption">倾听与洞察</div><nav>{nav.slice(0, 5).map(([id, Icon, name]) => <button key={id} className={page === id ? 'active' : ''} onClick={() => changePage(id)}><Icon size={19} /><span>{name}</span>{page === id && <i />}</button>)}<div className="nav-caption">管理</div>{nav.slice(5).map(([id, Icon, name]) => <button key={id} className={page === id ? 'active' : ''} onClick={() => changePage(id)}><Icon size={19} /><span>{name}</span></button>)}</nav><div className="sidebar-bottom"><div className="model-state"><i className={health?.configured ? '' : 'offline'} /><span>{health?.model || '尚未配置模型'}</span><small>本机版</small></div><div className="sidebar-profile"><span>我</span><div><strong>本地工作台</strong><small>让客户反馈推动改进</small></div></div></div></aside>
    <main className="main-area"><div className="topbar"><div className="row"><button className="icon-button mobile-toggle" onClick={() => setMobileNav(true)} aria-label="展开导航"><Menu size={22} /></button><span>工作台</span><ChevronRight size={13} /><strong>{meta[2]}</strong></div><div className="row topbar-right"><span className="connection-dot" /><span>本地运行</span><span className="topbar-divider" /><Globe2 size={15} /><span>多语言分析</span></div></div><div className="page-content"><header className="page-header"><div><div className="eyebrow">VOICE OF CUSTOMER</div><h1>{meta[2]}</h1><p>{meta[3]}</p></div>{!['stores', 'settings', 'model', 'executive'].includes(page) && <button className="button" onClick={() => setIntake(true)}><Plus size={18} />添加反馈</button>}</header><ErrorBox error={healthError || workspaceError || storeError} />
    {!['stores', 'settings', 'model', 'executive'].includes(page) && <div className="filter-bar"><div className="filter-selects"><label className="filter-select"><Building2 size={15} /><select aria-label="筛选门店" value={store} onChange={e => setStore(e.target.value)}><option value="">全部门店</option>{(stores || []).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label><label className="filter-select"><select aria-label="时间范围" value={range} onChange={e => setRange(e.target.value)}><option value="all">全部时间</option><option value="7">最近7天</option><option value="30">最近30天</option><option value="90">最近90天</option></select></label></div><label className="search-box"><Search size={16} /><input aria-label="搜索标题或原文" placeholder="搜索标题或原文" value={search} onChange={e => setSearch(e.target.value)} />{search && <button className="icon-button" aria-label="清空搜索" onClick={() => setSearch('')}><X size={14} /></button>}</label></div>}
    {page === 'executive' && <Executive key={workspace} query={query} revision={revision} open={setRecord} selectWorkspace={selectWorkspace} workspaces={workspaces || []} intake={() => setIntake(true)} store={store} stores={stores || []} setStore={setStore} search={search} setSearch={setSearch} />}{page === 'dashboard' && <Dashboard query={query} revision={revision} open={setRecord} intake={() => setIntake(true)} changePage={changePage} />}{page === 'records' && <Records query={query} revision={revision} open={setRecord} intake={() => setIntake(true)} />}{page === 'events' && <Events query={query} revision={revision} open={setRecord} themes={health?.themes || []} />}{page === 'reports' && <Reports workspace={workspace} scope={scope} revision={revision} open={setReport} changed={changed} />}{page === 'stores' && <Stores stores={stores || []} workspace={workspace} changed={changed} />}{page === 'model' && <ModelSettings changed={changed} />}{page === 'settings' && <Workspace workspace={workspace} workspaces={workspaces || []} health={health} changed={changed} select={selectWorkspace} />}
    <footer className="page-footer"><span>VOC · 客户原声工作台</span><span>证据在前，行动在后。</span></footer></div></main><Toast value={toast} />{intake && <Intake workspace={workspace} stores={stores || []} defaultStore={store} close={() => setIntake(false)} done={changed} />}{record && <EvidenceDrawer recordId={record} workspace={workspace} themes={health?.themes || []} close={() => setRecord(null)} changed={changed} />}{report && <ReportDetail reportId={report} workspace={workspace} close={() => setReport(null)} openRecord={id => { setReport(null); setRecord(id) }} changed={changed} />}
  </div>
}
