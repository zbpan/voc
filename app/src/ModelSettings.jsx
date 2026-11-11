import React, { useEffect, useState } from 'react'
import { Check, KeyRound, LoaderCircle, Save, ShieldCheck, Unplug } from 'lucide-react'
import { api, ErrorBox, Loading } from './shared.jsx'
import './model-settings.css'

export function ModelSettings({ changed }) {
  const [form, setForm] = useState(null)
  const [status, setStatus] = useState(null)
  const [key, setKey] = useState('')
  const [clearKey, setClearKey] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState('')
  const [busy, setBusy] = useState('')
  useEffect(() => {
    let active = true
    api('/api/settings/model').then(data => { if (active) { setStatus(data); setForm({ base_url: data.base_url, model: data.model, region: data.region }) } }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [])
  function edit(field, value) { setForm(current => ({ ...current, [field]: value })); setResult('') }
  async function submit(action) {
    setBusy(action); setError(''); setResult('')
    try {
      const payload = { ...form, api_key: key || null, clear_api_key: clearKey }
      const data = await api(`/api/settings/model${action === 'test' ? '/test' : ''}`, { method: action === 'test' ? 'POST' : 'PUT', headers: { 'X-VOC-Settings': '1' }, body: JSON.stringify(payload) })
      if (action === 'save') {
        setStatus(data); setKey(''); setClearKey(false); setResult('配置已保存在本机，新任务将使用该配置。'); changed()
      } else setResult('文本连接测试通过。测试未保存配置；语音和图片能力仍需用对应素材验证。')
    } catch (e) { setError(e.message) } finally { setBusy('') }
  }
  if (!form) return error ? <ErrorBox error={error} /> : <Loading />
  return <div className="model-settings-layout">
    <section className="panel model-config-panel">
      <div className="model-config-heading"><h2>连接你的模型服务</h2><p>兼容流式 Chat Completions 接口。填写自己的服务地址与模型名称。</p></div>
      <form onSubmit={e => { e.preventDefault(); submit('save') }}>
        <fieldset disabled={!!busy}>
          <label>API 基础地址<input type="url" required maxLength={500} value={form.base_url} onChange={e => edit('base_url', e.target.value)} placeholder="https://your-provider.example/v1" autoComplete="off" spellCheck="false" /><span className="field-note">通常以 /v1 结尾，不包含 /chat/completions。非本机服务必须使用 HTTPS。</span></label>
          <div className="model-config-fields"><label>模型名称<input required maxLength={160} value={form.model} onChange={e => edit('model', e.target.value)} placeholder="你的模型 ID" autoComplete="off" spellCheck="false" /></label><label>地域备注<input required maxLength={80} value={form.region} onChange={e => edit('region', e.target.value)} placeholder="例如：cn-beijing / local" /><span className="field-note">仅作标识，不会自动切换服务地址。</span></label></div>
          <label>API 密钥<input type="password" maxLength={2048} value={key} onChange={e => { setKey(e.target.value); setClearKey(false); setResult('') }} placeholder={status.configured ? '已配置；留空保留现有密钥' : '输入 API Key'} autoComplete="new-password" spellCheck="false" disabled={clearKey} /><span className="field-note">保存后不会回显密钥。更换服务地址时，必须重新填写密钥或明确清除。</span></label>
          <label className="model-clear-key"><input type="checkbox" checked={clearKey} onChange={e => { setClearKey(e.target.checked); setKey(''); setResult('') }} />清除已保存的密钥</label>
        </fieldset>
        <ErrorBox error={error} />
        {result && <div className="model-config-success" role="status"><Check size={18} /><span>{result}</span></div>}
        <div className="model-config-actions"><button className="button" type="button" disabled={!!busy} onClick={() => submit('test')}>{busy === 'test' ? <LoaderCircle className="spin" size={17} /> : <Unplug size={17} />}{busy === 'test' ? '正在测试…' : '测试文本连接'}</button><button className="button primary" type="submit" disabled={!!busy}>{busy === 'save' ? <LoaderCircle className="spin" size={17} /> : <Save size={17} />}保存配置</button></div>
      </form>
    </section>
    <aside className="model-config-aside">
      <section className="model-storage-note"><ShieldCheck size={24} strokeWidth={1.5} /><h2>密钥留在本机</h2><p>后端保存密钥，不在页面回显，也不持久化到浏览器存储。</p><details><summary>查看存储与安全说明</summary><p>密钥以明文保存在数据目录的 model-config.json 中，并非加密保险箱。请保护操作系统账户，不要分享数据目录或将其提交到 Git。</p></details><div className="model-config-status"><KeyRound size={16} /><span>{status.configured ? '当前已配置密钥' : '当前未配置密钥'}</span></div></section>
      <section className="model-capability-note"><h3>按任务选择能力</h3><p>文字与报告需要结构化输出。语音需要 input_audio，图片需要 image_url，需分别验证。</p><p>连接测试仅发送固定短文本，可能产生少量费用，不代表多模态能力已通过验证。</p></section>
    </aside>
  </div>
}
