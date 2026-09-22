import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getReveal, postReveal, putPreferences } from '../api.js'

const EMPTY_PREF = { wishes: '', dislikes: '', sizes: '', filled: false, updated_at: null }

// 只读偏好卡：展示本人（锁定后）或收礼对象（揭晓成功时）的内容
function PrefCard({ pref, emptyHint }) {
  if (!pref || !pref.filled) {
    return (
      <div className="pref-card">
        <p className="hint">{emptyHint}</p>
      </div>
    )
  }
  return (
    <div className="pref-card">
      {pref.wishes && (
        <div className="pref-row">
          <span className="pref-label">🎁 想要</span>
          <p className="pref-text">{pref.wishes}</p>
        </div>
      )}
      {pref.dislikes && (
        <div className="pref-row">
          <span className="pref-label">🚫 忌讳</span>
          <p className="pref-text">{pref.dislikes}</p>
        </div>
      )}
      {pref.sizes && (
        <div className="pref-row">
          <span className="pref-label">📏 尺码备注</span>
          <p className="pref-text">{pref.sizes}</p>
        </div>
      )}
    </div>
  )
}

export default function RevealPage() {
  const { token } = useParams()
  const [info, setInfo] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const [wishes, setWishes] = useState('')
  const [dislikes, setDislikes] = useState('')
  const [sizes, setSizes] = useState('')
  const [savedAt, setSavedAt] = useState(null)
  const [prefError, setPrefError] = useState('')
  const [savingPref, setSavingPref] = useState(false)

  useEffect(() => {
    getReveal(token)
      .then((data) => {
        setInfo(data)
        const pref = data.preference || EMPTY_PREF
        setWishes(pref.wishes)
        setDislikes(pref.dislikes)
        setSizes(pref.sizes)
        setSavedAt(pref.updated_at)
      })
      .catch((err) => setError(err.message))
  }, [token])

  async function savePreferences(e) {
    e.preventDefault()
    setPrefError('')
    setSavingPref(true)
    try {
      const pref = await putPreferences(token, { wishes, dislikes, sizes })
      setWishes(pref.wishes)
      setDislikes(pref.dislikes)
      setSizes(pref.sizes)
      setSavedAt(pref.updated_at)
      setInfo((prev) => (prev ? { ...prev, preference: pref } : prev))
    } catch (err) {
      setPrefError(err.message)
    } finally {
      setSavingPref(false)
    }
  }

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

  const ownPref = info.preference || EMPTY_PREF

  return (
    <div className="card center">
      <h1>{info.event_name}</h1>

      {info.status !== 'drawn' && (
        <>
          <p className="person-label">你好，{info.participant_name}</p>
          <span className="badge badge-pending">待抽签</span>
          <p className="hint">抽签尚未完成。在等待期间可以填写你的礼物偏好卡，抽签前可反复修改；抽签完成后将自动锁定。</p>

          <form className="pref-form" onSubmit={savePreferences}>
            <label className="field">
              <span>🎁 想要什么（兴趣、心愿、类型…）</span>
              <textarea
                rows={3}
                value={wishes}
                maxLength={2000}
                onChange={(e) => setWishes(e.target.value)}
                placeholder="例如：香薰蜡烛、悬疑小说、桌游"
              />
            </label>
            <label className="field">
              <span>🚫 忌讳 / 不想要什么（过敏原、忌口、雷区…）</span>
              <textarea
                rows={3}
                value={dislikes}
                maxLength={2000}
                onChange={(e) => setDislikes(e.target.value)}
                placeholder="例如：对坚果过敏、不喝酒、不收香水"
              />
            </label>
            <label className="field">
              <span>📏 尺码备注（衣物、鞋、戒指等）</span>
              <textarea
                rows={2}
                value={sizes}
                maxLength={2000}
                onChange={(e) => setSizes(e.target.value)}
                placeholder="例如：上衣 L / 鞋码 41 / 戒指 13 号"
              />
            </label>
            <button className="primary" disabled={savingPref}>
              {savingPref ? '保存中…' : (ownPref.filled ? '保存修改' : '保存偏好卡')}
            </button>
            {prefError && <div className="error">{prefError}</div>}
            <p className="hint">
              {savedAt
                ? `偏好卡已保存，最后修改 ${new Date(savedAt).toLocaleString()}。抽签前随时可以回来修改。`
                : '偏好卡内容只有抽中你的人会在揭晓时看到，组织者无法查看。'}
            </p>
          </form>
        </>
      )}

      {info.status === 'drawn' && info.revealed && !result && (
        <>
          <p className="person-label">你好，{info.participant_name}</p>
          <div className="error">
            该链接已经揭晓过了。结果只能成功揭晓一次，请通过你自己的记录查看。
          </div>
          <div className="pref-locked">
            <h2>我的偏好卡（已锁定）</h2>
            <PrefCard pref={ownPref} emptyHint="你在抽签前未填写偏好卡。" />
          </div>
        </>
      )}

      {info.status === 'drawn' && !info.revealed && !result && (
        <>
          <p className="person-label">你好，{info.participant_name}</p>
          <div className="pref-locked">
            <h2>我的偏好卡（已随抽签锁定）</h2>
            <PrefCard pref={ownPref} emptyHint="你在抽签前未填写偏好卡。" />
          </div>
          <p className="hint">点击下方按钮揭晓你要送出礼物的对象。<strong>请注意：结果只会显示这一次。</strong></p>
          <button className="primary big" onClick={reveal} disabled={busy}>
            {busy ? '揭晓中…' : '🎁 揭晓我的赠礼对象'}
          </button>
          {error && <div className="error">{error}</div>}
        </>
      )}

      {result && (
        <div className="result">
          <p className="person-label">你好，{result.participant_name}</p>
          <p className="hint">在「{result.event_name}」中，你要送出礼物的对象是：</p>
          <div className="recipient">🎉 {result.recipient_name}</div>

          <h2>{result.recipient_name} 的礼物偏好卡</h2>
          <PrefCard
            pref={result.recipient_preference}
            emptyHint="对方在抽签前未填写偏好卡，可按你的心意准备礼物。"
          />

          <p className="hint">请立刻记下结果与偏好信息，离开本页后将无法再次查看。</p>
        </div>
      )}
    </div>
  )
}
