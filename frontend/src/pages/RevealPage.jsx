import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getReveal, postReveal } from '../api.js'

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

  return (
    <div className="card center">
      <h1>{info.event_name}</h1>

      {info.status !== 'drawn' && (
        <>
          <p className="hint">抽签尚未完成，请等待组织者发起抽签后再回来揭晓。</p>
          <span className="badge badge-pending">待抽签</span>
        </>
      )}

      {info.status === 'drawn' && info.revealed && !result && (
        <>
          <p className="person-label">你好，{info.participant_name}</p>
          <div className="error">
            该链接已经揭晓过了。结果只能成功揭晓一次，请通过你自己的记录查看。
          </div>
        </>
      )}

      {info.status === 'drawn' && !info.revealed && !result && (
        <>
          <p className="person-label">你好，{info.participant_name}</p>
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
          <p className="hint">请立刻记下结果，离开本页后将无法再次查看。</p>
        </div>
      )}
    </div>
  )
}
