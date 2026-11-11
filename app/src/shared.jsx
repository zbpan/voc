import React, { useEffect, useRef, useState } from 'react'
import { AlertCircle, Check, LoaderCircle, Mic, Square, X } from 'lucide-react'

export async function api(url, options = {}) {
  const response = await fetch(url, { ...options, headers: { ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...options.headers } })
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try { const data = await response.json(); message = typeof data.detail === 'string' ? data.detail : data.detail?.map(x => x.msg).join('；') || message } catch {}
    throw new Error(message)
  }
  return response.json()
}

export function useData(url, revision = 0, interval = 0) {
  const [state, setState] = useState({ data: null, error: '', loading: true })
  useEffect(() => {
    if (!url) { setState({ data: null, error: '', loading: false }); return }
    let active = true
    const controller = new AbortController()
    let timer
    setState(s => ({ ...s, loading: true, error: '' }))
    async function load() {
      try {
        const data = await api(url, { signal: controller.signal })
        if (active) setState({ data, error: '', loading: false })
      } catch (error) { if (active) setState(s => ({ ...s, error: error.message, loading: false })) }
      if (active && interval) timer = setTimeout(load, interval)
    }
    load()
    return () => { active = false; controller.abort(); clearTimeout(timer) }
  }, [url, revision, interval])
  return state
}

export const labels = {
  queued: '排队中', processing: '分析中', completed: '已完成', failed: '处理失败',
  positive: '正向', negative: '负向', neutral: '中性', mixed: '褒贬并存',
  low: '低', medium: '中', high: '高', critical: '紧急',
  pending: '待复核', confirmed: '已确认', dismissed: '已排除',
  new: '待跟进', in_progress: '跟进中', resolved: '已解决',
  voice_message: '语音留言', call: '客服通话', interview: '访谈录音', text: '文字反馈', image: '图片反馈', audio: '语音', multimodal: '多模态反馈',
  customer: '客户', unknown: '身份待核实', agent: '坐席', zh: '中文', en: '英语', ar: '阿拉伯语',
}
export const label = value => labels[value] || value || '—'
export const time = seconds => `${Math.floor((seconds || 0) / 60).toString().padStart(2, '0')}:${Math.floor((seconds || 0) % 60).toString().padStart(2, '0')}`
export const dateTime = value => value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '—'
export const count = value => (value || 0).toLocaleString('zh-CN')

export function Badge({ value, children }) { return <span className={`badge badge-${value}`}>{children || label(value)}</span> }
export function ErrorBox({ error }) { return error ? <div className="error-box" role="alert"><AlertCircle size={17} /><span>{error}</span></div> : null }
export function Loading() { return <div className="loading"><LoaderCircle size={21} className="spin" />正在读取…</div> }
export function Empty({ icon: Icon, title, detail, action }) { return <div className="empty">{Icon && <Icon size={30} strokeWidth={1.4} />}<h3>{title}</h3><p>{detail}</p>{action}</div> }

export function Modal({ title, children, close, wide = false }) {
  const ref = useRef(null)
  useEffect(() => {
    const dialog = ref.current
    dialog.showModal()
    return () => { if (dialog.open) dialog.close() }
  }, [])
  return <dialog ref={ref} className={`modal ${wide ? 'modal-wide' : ''}`} onCancel={e => { e.preventDefault(); close() }} onClick={e => { if (e.target === e.currentTarget) close() }}>
    <div className="modal-head"><h2>{title}</h2><button className="icon-button" aria-label="关闭" onClick={close}><X size={21} /></button></div>{children}
  </dialog>
}

export function Recorder({ onFile }) {
  const [recording, setRecording] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState('')
  const recorder = useRef(null)
  const stream = useRef(null)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false; if (recorder.current?.state === 'recording') recorder.current.stop(); stream.current?.getTracks().forEach(t => t.stop()) } }, [])
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])
  useEffect(() => {
    if (!recording) return
    const timer = setInterval(() => setSeconds(value => value + 1), 1000)
    return () => clearInterval(timer)
  }, [recording])
  useEffect(() => { if (seconds >= 300 && recorder.current?.state === 'recording') recorder.current.stop() }, [seconds])
  async function start() {
    setError('')
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('当前浏览器不支持录音，请使用Chrome/Edge并通过localhost或HTTPS访问。')
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (!alive.current) { stream.current.getTracks().forEach(t => t.stop()); return }
      const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'].find(t => MediaRecorder.isTypeSupported(t))
      const instance = new MediaRecorder(stream.current, mimeType ? { mimeType } : undefined)
      recorder.current = instance
      const parts = []
      instance.ondataavailable = e => { if (e.data.size) parts.push(e.data) }
      instance.onstop = () => {
        stream.current?.getTracks().forEach(t => t.stop())
        if (!alive.current) return
        setRecording(false)
        const blob = new Blob(parts, { type: instance.mimeType })
        const ext = instance.mimeType.includes('mp4') ? 'm4a' : instance.mimeType.includes('ogg') ? 'ogg' : 'webm'
        const file = new File([blob], `网页录音-${Date.now()}.${ext}`, { type: blob.type })
        setPreview(URL.createObjectURL(blob)); onFile(file)
      }
      setPreview(''); onFile(null); setSeconds(0); setRecording(true); instance.start(1000)
    } catch (e) { stream.current?.getTracks().forEach(t => t.stop()); setError(e.name === 'NotAllowedError' ? '麦克风权限未开启，请在地址栏允许后重试。' : e.message) }
  }
  return <div className="recorder"><button type="button" className={`record-button ${recording ? 'recording' : ''}`} onClick={() => recording ? recorder.current.stop() : start()} aria-label={recording ? '结束录音' : '开始录音'}>{recording ? <Square size={24} fill="currentColor" /> : <Mic size={26} />}</button><strong>{recording ? `正在录音 ${time(seconds)}` : preview ? '录音已就绪' : '点击开始说话'}</strong><span className="muted">{recording ? '点击停止后可回听' : '每次最长5分钟，保留原始语言'}</span>{preview && <audio controls src={preview} />}<ErrorBox error={error} /></div>
}

export function Toast({ value }) { return value ? <div className="toast" role="status"><Check size={17} />{value}</div> : null }
