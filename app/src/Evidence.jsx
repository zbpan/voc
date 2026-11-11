import React, { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, Download, FileText, Headphones, Play, RefreshCw, Save, Trash2 } from 'lucide-react'
import { api, Badge, dateTime, Empty, ErrorBox, label, Loading, Modal, time, useData } from './shared.jsx'

function EventEditor({ event, workspace, themes, play, saved }) {
  const [draft, setDraft] = useState(event)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(false)
  useEffect(() => setDraft(event), [event.id, event.version])
  const change = (key, value) => setDraft(d => ({ ...d, [key]: value }))
  async function save(changes = {}) {
    setBusy(true); setError('')
    try {
      const body = Object.fromEntries(['title', 'theme', 'severity', 'sentiment', 'review_status', 'workflow_status', 'owner', 'notes', 'version'].map(key => [key, draft[key]]))
      await api(`/api/events/${event.id}?workspace_id=${workspace}`, { method: 'PATCH', body: JSON.stringify({ ...body, ...changes }) })
      setEditing(false); saved('事件已更新')
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <article className={`evidence-event ${event.review_status === 'dismissed' ? 'dismissed' : ''}`}>
    <div className="row spread"><div className="row wrap"><Badge value={event.severity}>{label(event.severity)}严重度</Badge><span className="tiny muted">{event.theme}</span><Badge value={event.review_status} /></div><Badge value={event.workflow_status} /></div>
    <h3>{event.title}</h3><blockquote dir="auto">{event.quote}</blockquote><p>{event.summary}</p>
    <div className="evidence-links">{event.evidence.map((e, i) => <button key={i} className="text-button" onClick={() => play(e)} disabled={e.precision !== 'chunk'}>{e.precision === 'chunk' ? <><Play size={14} />回听 {time(e.start)}–{time(e.end)}</> : <><FileText size={14} />文字原文</>}</button>)}<span className="tiny muted">{label(event.role)}</span></div>
    <div className="recommendation"><span>建议</span><p>{event.recommendation}</p></div>
    {event.owner && <div className="tiny muted">跟进人：{event.owner}</div>}{event.notes && <p className="saved-notes">跟进记录：{event.notes}</p>}
    <div className="row wrap action-row">{event.review_status === 'pending' && <button className="button small" disabled={busy} onClick={() => save({ review_status: 'confirmed' })}><Check size={14} />确认有效</button>}<button className="text-button" onClick={() => setEditing(!editing)}>复核与跟进<ChevronDown size={14} /></button></div>
    {editing && <div className="event-editor"><label>事件标题<input value={draft.title} maxLength={160} onChange={e => change('title', e.target.value)} /></label><div className="form-grid">
      <label>主题<select value={draft.theme} onChange={e => change('theme', e.target.value)}>{themes.map(t => <option key={t}>{t}</option>)}</select></label>
      {[['severity', '严重度', ['low', 'medium', 'high', 'critical']], ['sentiment', '情绪', ['positive', 'neutral', 'negative', 'mixed']], ['review_status', '复核结果', ['pending', 'confirmed', 'dismissed']], ['workflow_status', '跟进状态', ['new', 'in_progress', 'resolved']]].map(([key, name, values]) => <label key={key}>{name}<select aria-label={name} value={draft[key]} onChange={e => change(key, e.target.value)}>{values.map(v => <option value={v} key={v}>{label(v)}</option>)}</select></label>)}<label>跟进人<input value={draft.owner} maxLength={80} onChange={e => change('owner', e.target.value)} placeholder="填写姓名或团队" /></label></div><label>跟进记录<textarea aria-label="跟进记录" value={draft.notes} maxLength={4000} rows={3} onChange={e => change('notes', e.target.value)} placeholder="记录核查结论、改进措施与后续结果" /></label><button className="button primary small" disabled={busy || !draft.title.trim()} onClick={() => save()}><Save size={15} />{busy ? '保存中…' : '保存更改'}</button></div>}<ErrorBox error={error} />
  </article>
}

export function EvidenceDrawer({ recordId, workspace, themes, close, changed }) {
  const [revision, setRevision] = useState(0)
  const { data: record, error, loading } = useData(`/api/records/${recordId}?workspace_id=${workspace}`, revision, 5000)
  const [tab, setTab] = useState('events')
  const [playhead, setPlayhead] = useState(0)
  const [actionError, setActionError] = useState('')
  const [deleting, setDeleting] = useState(false)
  const audio = useRef(null)
  const stopAt = useRef(null)
  function saved(message) { setRevision(v => v + 1); changed(message) }
  function play(e) {
    if (!audio.current) return
    audio.current.currentTime = e.start; stopAt.current = e.end
    audio.current.play().catch(err => setActionError(err.message))
  }
  async function retry() {
    try { await api(`/api/records/${recordId}/retry?workspace_id=${workspace}`, { method: 'POST' }); saved('任务已重新排队') } catch (e) { setActionError(e.message) }
  }
  async function remove() {
    try { await api(`/api/records/${recordId}?workspace_id=${workspace}`, { method: 'DELETE' }); changed('反馈及其事件已删除'); close() } catch (e) { setActionError(e.message) }
  }
  return <Modal title="原声证据" close={close} wide><div className="drawer-body"><ErrorBox error={error || actionError} />{loading && !record ? <Loading /> : record && <>
    <div className="row wrap"><Badge value={record.status} /><span className="tiny muted">{label(record.source_type)} · {record.store_name || '未分配门店'} · {dateTime(record.created_at)}</span></div><h2 className="record-title">{record.title}</h2>
    {record.submitted_text && record.metadata?.modalities?.includes('audio') && <section className="record-summary"><h4>住客文字附言</h4><p dir="auto">{record.submitted_text}</p></section>}
    {record.assets?.length > 0 && <section className="feedback-photos"><h4>随附图片 <span className="muted">{record.assets.length}张</span></h4><div className="photo-grid">{record.assets.map(asset => <figure key={asset.id}><a href={`/api/records/${recordId}/assets/${asset.id}?workspace_id=${workspace}`} target="_blank" rel="noreferrer"><img loading="lazy" src={`/api/records/${recordId}/assets/${asset.id}?workspace_id=${workspace}`} alt={asset.metadata.caption || '酒店场景模拟配图'} /></a><figcaption><span>{asset.metadata.caption || '模拟配图'}</span><span>{asset.metadata.author} · {asset.metadata.license}</span>{asset.metadata.source_page && <a href={asset.metadata.source_page} target="_blank" rel="noreferrer">图片来源与许可</a>}</figcaption></figure>)}</div></section>}
    {record.status === 'failed' && <><ErrorBox error={record.error} /><button className="button small" onClick={retry}><RefreshCw size={15} />重试分析</button></>}
    {['queued', 'processing'].includes(record.status) && <div className="processing-block"><div className="row spread"><span>{record.stage}</span><span>{record.progress}%</span></div><progress max={100} value={record.progress} /></div>}
    {record.has_audio && <section className="audio-player"><div className="row spread"><span className="row"><Headphones size={16} />原始客户音轨</span><span className="tiny muted">{time(record.duration)}</span></div><div className="waveform" role="img" aria-label="由真实音频生成的波形">{record.waveform.map((v, i) => <span key={i} className={i / record.waveform.length <= playhead / record.duration ? 'played' : ''} style={{ height: `${Math.max(3, Math.sqrt(v) * 100)}%` }} />)}</div><audio ref={audio} controls preload="metadata" src={`/api/records/${recordId}/audio?workspace_id=${workspace}`} onTimeUpdate={e => { setPlayhead(e.target.currentTime); if (stopAt.current && e.target.currentTime >= stopAt.current) { e.target.pause(); stopAt.current = null } }} onSeeking={() => { if (stopAt.current && audio.current.currentTime > stopAt.current) stopAt.current = null }} /><p className="tiny muted">回听定位为实际处理片段（最长120秒），非逐字时间戳。</p></section>}
    {record.summary && <section className="record-summary"><h4>反馈摘要</h4><p>{record.summary}</p>{!record.is_feedback && <span className="tiny muted">模型未识别到产品或服务体验反馈，本条不产生体验事件。</span>}</section>}
    <div className="tabs"><button className={tab === 'events' ? 'active' : ''} onClick={() => setTab('events')}>体验事件 <span>{record.events.length}</span></button><button className={tab === 'transcript' ? 'active' : ''} onClick={() => setTab('transcript')}>完整转写</button><button className={tab === 'info' ? 'active' : ''} onClick={() => setTab('info')}>处理信息</button></div>
    {tab === 'events' ? record.events.length ? <div className="events-detail">{record.events.map(event => <EventEditor key={`${event.id}-${event.version}`} event={event} workspace={workspace} themes={themes} play={play} saved={saved} />)}</div> : <Empty icon={FileText} title={record.status === 'completed' ? '本条没有提取到体验事件' : '分析结果将在这里出现'} detail={record.status === 'completed' ? '完整原文仍可在转写页查看。' : record.stage} /> : tab === 'transcript' ? <div className="transcript">{record.chunks.length ? record.chunks.map(chunk => <section key={chunk.id}>{record.has_audio && <button className="text-button" onClick={() => play(chunk)}><Play size={13} />{time(chunk.start)}–{time(chunk.end)}</button>}<p dir="auto">{chunk.transcript}</p></section>) : <p className="muted">暂无转写内容</p>}</div> : <div className="record-info"><dl><dt>分析模型</dt><dd>{record.model}</dd><dt>识别语言</dt><dd>{label(record.language)}</dd><dt>提示词版本</dt><dd>{record.prompt_version}</dd><dt>累计成功片段 Token</dt><dd>{(record.usage.total_tokens || 0).toLocaleString()}</dd><dt>处理次数</dt><dd>{record.attempts}</dd><dt>反馈标识</dt><dd className="mono">{record.id}</dd></dl>{['failed', 'completed'].includes(record.status) && <div className="delete-block">{deleting ? <><p>删除这条反馈、音频和关联事件？已生成的报告仍保留当时快照。</p><div className="row"><button className="button danger small" onClick={remove}>确认删除</button><button className="text-button" onClick={() => setDeleting(false)}>取消</button></div></> : <button className="text-button danger-text" onClick={() => setDeleting(true)}><Trash2 size={14} />删除此条反馈</button>}</div>}</div>}
  </>}</div></Modal>
}

export function ReportDetail({ reportId, workspace, close, openRecord, changed }) {
  const [revision, setRevision] = useState(0)
  const { data: report, error, loading } = useData(`/api/reports/${reportId}?workspace_id=${workspace}`, revision, 5000)
  const [actionError, setActionError] = useState('')
  async function retry() { try { await api(`/api/reports/${reportId}/retry?workspace_id=${workspace}`, { method: 'POST' }); setRevision(v => v + 1); changed('报告已重新排队') } catch (e) { setActionError(e.message) } }
  const executive = report?.snapshot?.executive
  return <Modal title="洞察报告" close={close} wide><div className="report-document"><ErrorBox error={error || actionError} />{loading && !report ? <Loading /> : report && <><div className="row spread wrap"><span className="eyebrow">客户原声 / 运营洞察</span><Badge value={report.status} /></div><h1>{report.title}</h1><p className="tiny muted">{dateTime(report.created_at)} · {report.model} · 生成时快照</p>
    {report.status === 'completed' ? <><div className="report-numbers"><div><strong>{report.snapshot.metrics.records}</strong><span>原始反馈</span></div><div><strong>{report.snapshot.metrics.events}</strong><span>有效事件</span></div><div><strong>{report.snapshot.metrics.pending_review}</strong><span>待复核</span></div></div><p className="report-lead">{report.content.summary}</p>{executive && <section className="report-section"><h2>全量经营对照</h2><p className="tiny muted">本期 {executive.period.start} 至 {executive.period.end}；前期 {executive.period.previous_start} 至 {executive.period.previous_end}</p><p>本期负向反馈 {executive.metrics.negative}/{executive.metrics.feedback}，占比 {executive.metrics.negative_rate == null ? '暂无数据' : `${executive.metrics.negative_rate}%`}；前期 {executive.metrics.previous.negative}/{executive.metrics.previous.feedback}。门店与议题指标采用全量记录计算。</p></section>}{report.snapshot.sampled && <p className="field-note">范围内共{report.snapshot.total_events}条事件，报告按严重度排序引用前200条；经营聚合使用全量记录。</p>}{[['priorities', '优先关注'], ['strengths', '正向体验'], ['actions', '行动建议']].map(([key, title]) => <section className="report-section" key={key}><h2>{title}</h2>{report.content[key].length ? report.content[key].map((item, i) => <article key={i}><h3>{item.title}</h3><p>{item.detail}</p><div className="citation-list">{item.event_ids.map(id => { const event = report.snapshot.events.find(e => e.id === id); return <button key={id} className="text-button" onClick={() => openRecord(event.record_id)}><FileText size={13} />{event.title}</button> })}</div></article>) : <p className="muted">本次样本暂无充分证据。</p>}</section>)}<div className="report-source"><p>范围：{report.scope.start || '不限开始日期'} 至 {report.scope.end || '生成时'}；默认排除已排除事件。报告建议需结合原声及人工核查判断。</p><p>Session ID：{report.session_id}</p></div><a className="button primary" href={`/api/reports/${reportId}/export?workspace_id=${workspace}`}><Download size={17} />下载 Markdown 报告</a></> : report.status === 'failed' ? <><ErrorBox error={report.error} /><button className="button" onClick={retry}><RefreshCw size={16} />重试生成</button></> : <div className="empty"><Loading /><p>正在根据事件快照生成带证据的经营报告，可关闭后继续工作。</p></div>}
  </>}</div></Modal>
}
