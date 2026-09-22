import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createEvent } from '../api.js'

// 创建活动：名称、参与者（每行一个）、禁配关系（每行“甲, 乙”，可先为空后补）
export default function HomePage() {
  const navigate = useNavigate()
  const [name, setName] = useState('秘密赠礼')
  const [namesText, setNamesText] = useState('')
  const [pairsText, setPairsText] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')

    const participants = Array.from(
      new Set(
        namesText
          .split(/[\n,，、]/)
          .map((s) => s.trim())
          .filter(Boolean),
      ),
    )
    if (participants.length < 2) {
      setError('请至少填写 2 名参与者（每行一个名字）')
      return
    }

    const forbiddenPairs = []
    const badLines = []
    pairsText
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
      .forEach((line, i) => {
        const parts = line.split(/[,，、]/).map((s) => s.trim()).filter(Boolean)
        if (parts.length === 2 && parts[0] !== parts[1] && participants.includes(parts[0]) && participants.includes(parts[1])) {
          forbiddenPairs.push(parts)
        } else {
          badLines.push(i + 1)
        }
      })
    if (badLines.length) {
      setError(`第 ${badLines.join('、')} 行禁配关系无效：须为两名已填写的不同参与者`)
      return
    }

    setBusy(true)
    try {
      const event = await createEvent({ name: name.trim() || '秘密赠礼', participants, forbiddenPairs })
      localStorage.setItem(`organizer_token_${event.id}`, event.organizer_token)
      navigate(`/event/${event.id}?token=${encodeURIComponent(event.organizer_token)}`)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h1>发起一场秘密赠礼</h1>
      <p className="hint">录入参与者与禁配关系后即可抽签。系统保证每人恰好送出、收到一份礼物，且无人抽中自己或禁配对象。</p>

      <label className="field">
        <span>活动名称</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
      </label>

      <label className="field">
        <span>参与者（每行一个名字，至少 2 人）</span>
        <textarea
          rows={8}
          value={namesText}
          onChange={(e) => setNamesText(e.target.value)}
          placeholder={'张三\n李四\n王五\n赵六'}
        />
      </label>

      <label className="field">
        <span>禁配关系（可选，每行“甲, 乙”表示两人互不能抽中对方）</span>
        <textarea
          rows={4}
          value={pairsText}
          onChange={(e) => setPairsText(e.target.value)}
          placeholder={'张三, 李四\n王五, 赵六'}
        />
      </label>

      {error && <div className="error">{error}</div>}

      <button className="primary" disabled={busy}>{busy ? '创建中…' : '创建活动'}</button>
    </form>
  )
}
