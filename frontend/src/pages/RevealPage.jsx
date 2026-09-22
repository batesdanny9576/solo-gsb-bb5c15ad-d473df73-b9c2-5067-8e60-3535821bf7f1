import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getReveal, postReveal, savePreference } from '../api.js'

const EMPTY_CARD = { wish_text: '', avoid_text: '', size_text: '' }

// 只读展示一张偏好卡（本人锁定后的卡片 / 揭晓时对方的卡片）
function PreferenceCardView({ card }) {
  const empty = !card || (!card.wish_text && !card.avoid_text && !card.size_text)
  if (empty) return <p className="hint">未填写偏好卡。</p>
  return (
    <div className="pref-card">
      <div className="pref-row">
        <span className="pref-label">🎁 想要</span>
        <p className="pref-text">{card.wish_text || '—'}</p>
      </div>
      <div className="pref-row">
        <span className="pref-label">🚫 忌讳</span>
        <p className="pref-text">{card.avoid_text || '—'}</p>
      </div>
      <div className="pref-row">
        <span className="pref-label">📏 尺码备注</span>
        <p className="pref-text">{card.size_text || '—'}</p>
      </div>
    </div>
  )
}

// 抽签前由本人反复填写 / 修改
function PreferenceForm({ token, initial, onSaved }) {
  const [form, setForm] = useState(initial || EMPTY_CARD)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')

  function update(key, value) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setMsg('')
    setError('')
    try {
      const res = await savePreference(token, {
        wish_text: form.wish_text,
        avoid_text: form.avoid_text,
        size_text: form.size_text,
      })
      setMsg('已保存，抽签前可以随时回来修改。')
      onSaved(res)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="pref-form" onSubmit={submit}>
      <label className="field">
        <span>🎁 想要什么（愿望、兴趣方向）</span>
        <textarea
          rows={3}
          maxLength={1000}
          value={form.wish_text}
          onChange={(e) => update('wish_text', e.target.value)}
          placeholder="例如：香薰、桌游、科幻小说…"
        />
      </label>
      <label className="field">
        <span>🚫 忌讳什么（不想要 / 过敏 / 忌口）</span>
        <textarea
          rows={3}
          maxLength={1000}
          value={form.avoid_text}
          onChange={(e) => update('avoid_text', e.target.value)}
          placeholder="例如：花粉过敏、不吃香菜、不戴毛绒制品…"
        />
      </label>
      <label className="field">
        <span>📏 尺码备注（衣物 / 鞋码等）</span>
        <textarea
          rows={2}
          maxLength={1000}
          value={form.size_text}
          onChange={(e) => update('size_text', e.target.value)}
          placeholder="例如：上衣 L、鞋 42 码…"
        />
      </label>
      {msg && <div className="save-ok">✓ {msg}</div>}
      {error && <div className="error">{error}</div>}
      <button className="primary" disabled={busy}>
        {busy ? '保存中…' : '保存偏好卡'}
      </button>
    </form>
  )
}

export default function RevealPage() {
  const { token } = useParams()
  const [info, setInfo] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getReveal(token)
      .then(setInfo)
      .catch((err) => setError(err.message))
  }, [token])

  async function reveal() {
    setBusy(true)
    setError('')
    try {
      const r = await postReveal(token)
      setResult(r)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (error && !info) {
    return (
      <div className="card center">
        <h1>链接无效</h1>
        <p className="hint">{error}</p>
      </div>
    )
  }
  if (!info) return <div className="card">加载中…</div>

  const drawn = info.status === 'drawn'
  const ownCard = info.preference

  return (
    <div className="card center">
      <h1>{info.event_name}</h1>
      <p className="person-label">你好，{info.participant_name}</p>

      {/* 抽签前：填写 / 修改自己的偏好卡 */}
      {!drawn && (
        <div className="pref-section">
          <span className="badge badge-pending">待抽签</span>
          <p className="hint">
            抽签尚未完成。你可以先填写<strong>礼物偏好卡</strong>，
            抽签前随时可以回来修改；<strong>抽签完成后将锁定，无法再改。</strong>
            只有抽签后为你准备礼物的人，会在揭晓时看到这张卡片。
          </p>
          <PreferenceForm
            token={token}
            initial={ownCard ? {
              wish_text: ownCard.wish_text,
              avoid_text: ownCard.avoid_text,
              size_text: ownCard.size_text,
            } : EMPTY_CARD}
            onSaved={(res) =>
              setInfo((i) => ({
                ...i,
                preference_filled: res.preference_filled,
                preference: res.preference,
              }))
            }
          />
        </div>
      )}

      {/* 抽签后、尚未揭晓：可查看锁定后的本人卡片，并一次性揭晓对方 */}
      {drawn && info.revealed && !result && (
        <div className="pref-section">
          <div className="error">
            该链接已经揭晓过了。结果只能成功揭晓一次，请通过你自己的记录查看。
          </div>
          <h2>我的礼物偏好卡（已锁定）</h2>
          <PreferenceCardView card={ownCard} />
        </div>
      )}

      {drawn && !info.revealed && !result && (
        <div className="pref-section">
          <h2>我的礼物偏好卡（已锁定）</h2>
          <PreferenceCardView card={ownCard} />
          <p className="hint">
            抽签已完成。点击下方按钮揭晓你要送出礼物的对象，<strong>结果只会显示这一次</strong>。
          </p>
          <button className="primary big" onClick={reveal} disabled={busy}>
            {busy ? '揭晓中…' : '🎁 揭晓我的赠礼对象'}
          </button>
          {error && <div className="error">{error}</div>}
        </div>
      )}

      {/* 一次性成功揭晓：收礼人姓名 + 对方偏好卡 */}
      {result && (
        <div className="result pref-section">
          <p className="hint">在「{result.event_name}」中，你要送出礼物的对象是：</p>
          <div className="recipient">🎉 {result.recipient_name}</div>
          <h2>ta 的礼物偏好卡</h2>
          <PreferenceCardView card={result.recipient_preference} />
          <p className="hint">请立刻记下结果，离开本页后将无法再次查看。</p>
        </div>
      )}
    </div>
  )
}
