import React, { useEffect, useId, useState } from 'react'
import { ArrowRight, ChevronDown } from 'lucide-react'
import './improvements.css'

export function ImprovementAgenda({ items, openGroup, openBase, openExample }) {
  const prefix = useId()
  const snapshot = !openGroup
  const [expanded, setExpanded] = useState(snapshot ? null : items?.[0]?.kind)
  const [wide, setWide] = useState(() => window.matchMedia('(min-width: 761px)').matches)
  useEffect(() => {
    const query = window.matchMedia('(min-width: 761px)')
    const resize = e => setWide(e.matches)
    query.addEventListener('change', resize)
    return () => query.removeEventListener('change', resize)
  }, [])
  if (!items) return null
  return <section className="cx-agenda" aria-labelledby={`${prefix}-heading`}>
    <header><h2 id={`${prefix}-heading`}>本期改善清单</h2><span>{snapshot ? '生成报告时的观察' : '按当前门店与周期筛选'}</span></header>
    {!items.length && <p className="cx-agenda-empty">当前范围还没有足够依据提出改善建议。可扩大周期、选择全部门店，或复核已收到的体验事件。</p>}
    {items.map(item => {
      const active = expanded === item.kind
      const id = `${prefix}-${item.kind}`
      const examples = item.groups.map(g => ({ label: g.label, entry: g.example || g.entries?.[0] })).filter(g => g.entry)
      const shown = item.kind === 'transfer' ? examples : examples.slice(0, 1)
      const nextSteps = <dl className="cx-agenda-steps">
        <div><dt>一线可以怎么做</dt><dd>{item.customer_step}</dd></div>
        <div><dt>怎样复查</dt><dd>{item.check}</dd></div>
      </dl>
      return <article key={item.kind}>
        <h3><button type="button" className="cx-agenda-toggle" aria-expanded={active} aria-controls={id}
          onClick={() => setExpanded(active ? null : item.kind)}>
          <span className="cx-agenda-label">{item.label}</span>
          <span className="cx-agenda-title">{item.title}</span>
          <ChevronDown size={17} aria-hidden="true" />
        </button></h3>
        <div className="cx-agenda-body" id={id} hidden={!active}>
          <p className="cx-agenda-finding">{item.finding}</p>
          <dl className="cx-agenda-primary"><dt>管理者下一步</dt><dd>{item.manager_step}</dd></dl>
          <div className={shown.length > 1 ? 'cx-quote-pair' : undefined}>{shown.map(({ label, entry }) =>
            <figure className="cx-agenda-quote" key={label}>
              <figcaption>{entry.store_name} · {shown.length > 1 ? label : '代表反馈'} · {entry.review_status === 'confirmed' ? '事件已确认' : '事件待复核'}</figcaption>
              <details open={wide}><summary>{entry.title || '所引事件'}<small>查看原话</small></summary><blockquote dir="auto">{entry.quote}</blockquote></details>
            </figure>)}</div>
          {wide ? nextSteps : <details className="cx-agenda-more"><summary>一线试法与复查方法</summary>{nextSteps}</details>}
          <div className="cx-agenda-sources">{item.groups.filter(g => g.count > 0).map((g, i) =>
            <button key={i} type="button" className="text-button" onClick={() => snapshot ? openExample(g.example.record_id, g.example.event_id) : openGroup(item, g)}>
              {snapshot ? `${g.label} · ${g.count}条，看代表反馈` : `查看${g.label}反馈（${g.count}条）`}<ArrowRight size={14} aria-hidden="true" />
            </button>)}</div>
          {openBase && item.bases?.length > 0 && <details className="cx-agenda-bases"><summary>核对占比分母</summary><div className="cx-agenda-sources">{item.bases.map(b =>
            <button key={b.label} type="button" className="text-button" disabled={!b.count} onClick={() => openBase(item, b)}>{b.label} · {b.count}条<ArrowRight size={14} aria-hidden="true" /></button>
          )}</div></details>}
        </div>
      </article>
    })}
  </section>
}
