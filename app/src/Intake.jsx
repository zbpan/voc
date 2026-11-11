import React, { useState } from 'react'
import { ArrowRight, AudioLines, CheckCircle2, FileAudio, MessageSquareText, Mic, Upload, X } from 'lucide-react'
import { api, ErrorBox, Modal, Recorder, useData } from './shared.jsx'

export function Intake({ workspace, stores, defaultStore, close, done }) {
  const [mode, setMode] = useState('audio')
  const [files, setFiles] = useState([])
  const [store, setStore] = useState(defaultStore || '')
  const [source, setSource] = useState('voice_message')
  const [language, setLanguage] = useState('auto')
  const [channel, setChannel] = useState('mixed')
  const [text, setText] = useState('')
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')
  const [drag, setDrag] = useState(false)
  function selectFiles(list) {
    const chosen = Array.from(list)
    if (chosen.length + files.length > 20) { setError('每批最多导入20个文件'); return }
    if (chosen.some(f => f.size > 512 * 1024 * 1024)) { setError('单个文件不能超过512MB'); return }
    setError(''); setFiles(value => [...value, ...chosen])
  }
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('')
    let successes = 0
    try {
      if (mode === 'text') {
        await api('/api/records/text', { method: 'POST', body: JSON.stringify({ workspace_id: workspace, store_id: store || null, title: title || '文字反馈', text, language_hint: language, source_type: 'text' }) }); successes = 1
      } else {
        for (let i = 0; i < files.length; i++) {
          setProgress(`正在上传 ${i + 1}/${files.length}`)
          const data = new FormData()
          data.append('file', files[i]); data.append('workspace_id', workspace); data.append('store_id', store); data.append('source_type', source); data.append('language_hint', language); data.append('channel', channel)
          await api('/api/records/upload', { method: 'POST', body: data }); successes++
        }
      }
      done(`${successes}条反馈已进入分析队列`); close()
    } catch (e) { setFiles(value => value.slice(successes)); setError(`${successes ? `已有${successes}条上传成功。` : ''}${e.message}`); if (successes) done(`${successes}条反馈已进入分析队列`) }
    finally { setBusy(false); setProgress('') }
  }
  return <Modal title="添加客户反馈" close={() => !busy && close()} wide><form onSubmit={submit} className="modal-body">
    <div className="tabs">{[['audio', Upload, '上传录音'], ['record', Mic, '直接录音'], ['text', MessageSquareText, '文字反馈']].map(([id, Icon, name]) => <button type="button" key={id} className={mode === id ? 'active' : ''} disabled={busy} onClick={() => { setMode(id); setFiles([]); setError('') }}><Icon size={16} />{name}</button>)}</div>
    {mode === 'text' ? <><label>反馈标题<input value={title} maxLength={200} onChange={e => setTitle(e.target.value)} placeholder="例如：入住体验反馈" /></label><label>客户原文<textarea required rows={7} value={text} minLength={2} maxLength={20000} onChange={e => setText(e.target.value)} placeholder="粘贴客户的原始反馈，保留原语言…" /></label></> : mode === 'record' ? <Recorder onFile={file => setFiles(file ? [file] : [])} /> : <>
      <label className={`dropzone ${drag ? 'dragging' : ''}`} onDragOver={e => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)} onDrop={e => { e.preventDefault(); setDrag(false); if (!busy) selectFiles(e.dataTransfer.files) }}>
        <span className="upload-icon"><Upload size={24} /></span><strong>拖入录音，或点击选择文件</strong><span>WAV / MP3 / M4A / FLAC / OGG / WebM 等</span><small>单文件≤512MB、≤3小时，每批最多20个</small><input type="file" multiple disabled={busy} accept=".wav,.mp3,.m4a,.mp4,.flac,.ogg,.webm,.aac,.opus" onChange={e => { selectFiles(e.target.files); e.target.value = '' }} aria-label="选择录音文件" />
      </label>
      {files.length > 0 && <ul className="file-list">{files.map((f, i) => <li key={`${f.name}-${i}`}><FileAudio size={17} /><span>{f.name}<small>{(f.size / 1024 / 1024).toFixed(2)} MB</small></span><button type="button" className="icon-button" disabled={busy} aria-label={`移除${f.name}`} onClick={() => setFiles(value => value.filter((_, n) => n !== i))}><X size={16} /></button></li>)}</ul>}
    </>}
    <div className="form-grid"><label>归属门店<select value={store} onChange={e => setStore(e.target.value)}><option value="">暂不分配</option>{stores.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label><label>语言提示<select value={language} onChange={e => setLanguage(e.target.value)}>{[['auto', '自动识别'], ['zh', '中文'], ['en', '英语'], ['ar', '阿拉伯语'], ['es', '西班牙语'], ['ja', '日语'], ['th', '泰语']].map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select></label>
    {mode !== 'text' && <><label>录音来源<select value={source} onChange={e => setSource(e.target.value)}><option value="voice_message">语音留言</option><option value="call">客服通话</option><option value="interview">访谈录音</option></select></label><label>客户声道<select value={channel} onChange={e => setChannel(e.target.value)}><option value="mixed">自动判断 / 混合声道</option><option value="left">只分析左声道</option><option value="right">只分析右声道</option></select></label></>}
    </div><p className="field-note">提交后由 Qwen3.8-Omni 转写并提取体验事件。原始音频保存在本机，证据按实际音频片段定位。</p><ErrorBox error={error} /><div className="modal-foot"><span className="muted">{progress || (files.length ? `已选择 ${files.length} 个文件` : '保留每条反馈的原始证据')}</span><button className="button primary" disabled={busy || (mode === 'text' ? text.trim().length < 2 : !files.length)}>{busy ? progress || '正在提交…' : '提交并分析'}<ArrowRight size={17} /></button></div>
  </form></Modal>
}

export function Collection({ token }) {
  const { data: store, error: loadError } = useData(`/api/collect/${token}`)
  const [mode, setMode] = useState('record')
  const [text, setText] = useState('')
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState('')
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('')
    try {
      if (mode === 'text') await api(`/api/collect/${token}/text`, { method: 'POST', body: JSON.stringify({ text }) })
      else { const data = new FormData(); data.append('file', file); await api(`/api/collect/${token}/upload`, { method: 'POST', body: data }) }
      setSuccess(true)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <div className="collection-page"><div className="collection-brand"><span className="brand-mark"><AudioLines size={22} aria-hidden="true" /></span><span>VOC <small>客户原声</small></span></div><main className="collection-main"><div className="eyebrow">您的体验，值得认真对待</div><h1>{store?.name || '客户反馈'}</h1><p className="muted">{store?.region ? `${store.region} · ` : ''}说说这次体验，有什么让您满意，或值得改进？</p><ErrorBox error={loadError} />
    {success ? <div className="collection-success"><CheckCircle2 size={44} /><h2>谢谢，已经收到您的反馈</h2><p>您的声音将帮助我们做得更好。</p><button className="button" onClick={() => { setSuccess(false); setText(''); setFile(null) }}>再补充一条</button></div> : store && <form onSubmit={submit} className="collection-form"><div className="tabs">{[['record', '语音留言'], ['text', '文字反馈'], ['upload', '上传录音']].map(([v, t]) => <button key={v} type="button" className={mode === v ? 'active' : ''} onClick={() => { setMode(v); setFile(null) }}>{t}</button>)}</div>{mode === 'record' ? <Recorder onFile={setFile} /> : mode === 'text' ? <label>您的反馈<textarea required rows={7} minLength={2} maxLength={20000} placeholder="请用您习惯的语言告诉我们…" value={text} onChange={e => setText(e.target.value)} /></label> : <label className="collection-upload">选择音频<input type="file" accept="audio/*,.webm,.m4a" onChange={e => setFile(e.target.files[0])} /></label>}<p className="field-note">提交即同意将这条反馈用于服务改进，并由云端模型进行转写和分析。</p><ErrorBox error={error} /><button className="button primary full" disabled={busy || (mode === 'text' ? text.trim().length < 2 : !file)}>{busy ? '正在提交…' : '提交反馈'}<ArrowRight size={17} /></button></form>}
  </main><footer>VOC · 客户原声工作台</footer></div>
}
