import { useEffect, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import {
  addParticipant,
  deleteParticipant,
  drawEvent,
  getEvent,
  setForbiddenPairs,
} from '../api.js'

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      // 旧浏览器 / 非 HTTPS 兜底
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button type="button" className="link-btn" onClick={copy}>
      {copied ? '已复制 ✓' : '复制链接'}
    </button>
  )
}

export default function EventPage() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const [token, setToken] = useState(
    () => searchParams.get('token') || localStorage.getItem(`organizer_token_${id}`) || '',
  )
  const [tokenInput, setTokenInput] = useState('')
  const [event, setEvent] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const [newName, setNewName] = useState('')
  const [pairA, setPairA] = useState('')
  const [pairB, setPairB] = useState('')

  async function refresh() {
    const ev = await getEvent(id, token)
    setEvent(ev)
    return ev
  }

  useEffect(() => {
    if (!token) {
      setLoading(false)
      return
    }
    localStorage.setItem(`organizer_token_${id}`, token)
    setLoading(true)
    refresh()
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, token])

  function useTypedToken(e) {
    e.preventDefault()
    setToken(tokenInput.trim())
  }

  async function handleAddName(e) {
    e.preventDefault()
    setError('')
    if (!newName.trim()) return
    try {
      await addParticipant(id, token, newName.trim())
      setNewName('')
      await refresh()
    } catch (err) {
      setError(err.message)
    }
  }

  async function handleDeleteName(pid) {
    setError('')
    try {
      await deleteParticipant(id, token, pid)
      await refresh()
    } catch (err) {
      setError(err.message)
    }
  }

  async function putPairs(pairs) {
    try {
      const ev = await setForbiddenPairs(id, token, pairs)
      setEvent(ev)
    } catch (err) {
      setError(err.message)
    }
  }

  async function handleAddPair(e) {
    e.preventDefault()
    setError('')
    if (!pairA || !pairB || pairA === pairB) {
      setError('请选择两名不同的参与者')
      return
    }
    const pairs = event.forbidden_pairs.map((p) => [p.lower_name, p.higher_name])
    const key = [pairA, pairB].sort().join('|')
    if (pairs.some((p) => [...p].sort().join('|') === key)) {
      setError('该禁配关系已存在')
      return
    }
    pairs.push([pairA, pairB])
    await putPairs(pairs)
    setPairA('')
    setPairB('')
  }

  async function handleRemovePair(pid) {
    setError('')
    const pairs = event.forbidden_pairs
      .filter((p) => p.id !== pid)
      .map((p) => [p.lower_name, p.higher_name])
    await putPairs(pairs)
  }

  async function handleDraw() {
    setError('')
    if (!window.confirm('确认发起抽签？抽签完成后参与者名单与禁配关系将锁定。')) return
    try {
      await drawEvent(id, token)
      await refresh()
    } catch (err) {
      // 409 表示无解（或已抽），刷新以展示记录的无解原因
      await refresh().catch(() => {})
      setError(err.message)
    }
  }

  if (!token) {
    return (
      <div className="card">
        <h1>组织者入口</h1>
        <p className="hint">请输入创建活动时获得的组织者令牌（在管理链接的 token 参数中）。</p>
        <form onSubmit={useTypedToken} className="token-form">
          <input
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="组织者令牌"
          />
          <button className="primary">进入管理</button>
        </form>
      </div>
    )
  }

  if (loading) return <div className="card">加载中…</div>
  if (!event) return <div className="card error">{error || '活动不存在'}</div>

  const drawn = event.status === 'drawn'
  const fullLink = (path) => `${window.location.origin}${path}`

  return (
    <div className="card">
      <div className="event-head">
        <h1>{event.name}</h1>
        <span className={`badge ${drawn ? 'badge-done' : 'badge-pending'}`}>
          {drawn ? '已抽签' : '待抽签'}
        </span>
      </div>

      {event.failure_reason && (
        <div className="error">
          <strong>抽签无解：</strong>{event.failure_reason}
          <div className="hint">未产生任何匹配结果，可调整后重新发起抽签。</div>
        </div>
      )}
      {error && !event.failure_reason && <div className="error">{error}</div>}

      <section className="block">
        <h2>参与者（{event.participants.length} 人）</h2>
        <ul className="people">
          {event.participants.map((p) => (
            <li key={p.id}>
              <span className="person-name">{p.name}</span>
              {drawn ? (
                <span className="reveal-state">
                  {p.revealed ? (
                    <em className="revealed">已揭晓</em>
                  ) : (
                    <em className="unrevealed">尚未揭晓</em>
                  )}
                </span>
              ) : (
                <button className="link-btn danger" onClick={() => handleDeleteName(p.id)}>
                  删除
                </button>
              )}
            </li>
          ))}
        </ul>
        {!drawn && (
          <form className="inline-form" onSubmit={handleAddName}>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="新增参与者名字"
              maxLength={100}
            />
            <button>添加</button>
          </form>
        )}
      </section>

      <section className="block">
        <h2>禁配关系（互不能抽中对方）</h2>
        {event.forbidden_pairs.length === 0 && <p className="hint">暂无限配关系。</p>}
        <ul className="pairs">
          {event.forbidden_pairs.map((p) => (
            <li key={p.id} className="pair-row">
              <span>{p.lower_name} ⥃ {p.higher_name}</span>
              {!drawn && (
                <button className="link-btn danger" onClick={() => handleRemovePair(p.id)}>
                  移除
                </button>
              )}
            </li>
          ))}
        </ul>
        {!drawn && (
          <form className="inline-form" onSubmit={handleAddPair}>
            <select value={pairA} onChange={(e) => setPairA(e.target.value)}>
              <option value="">选择参与者</option>
              {event.participants.map((p) => (
                <option key={p.id} value={p.name}>{p.name}</option>
              ))}
            </select>
            <span className="pair-x">⥃</span>
            <select value={pairB} onChange={(e) => setPairB(e.target.value)}>
              <option value="">选择参与者</option>
              {event.participants.map((p) => (
                <option key={p.id} value={p.name}>{p.name}</option>
              ))}
            </select>
            <button>添加禁配</button>
          </form>
        )}
      </section>

      {!drawn && (
        <section className="block">
          <button className="primary big" onClick={handleDraw}>
            🎲 发起抽签
          </button>
          <p className="hint">存在无解可能（例如某人被所有人禁配），系统会明确说明且不产生部分结果。</p>
        </section>
      )}

      {drawn && (
        <section className="block">
          <h2>揭晓链接（分发给对应参与者）</h2>
          <p className="hint">
            每条链接只能成功揭晓一次；本页不会显示任何人的抽签结果，仅显示是否已揭晓。
          </p>
          <ul className="links">
            {event.participants.map((p) => (
              <li key={p.id}>
                <div className="link-row">
                  <strong>{p.name}</strong>
                  <span className={p.revealed ? 'revealed' : 'unrevealed'}>
                    {p.revealed ? '已揭晓' : '未揭晓'}
                  </span>
                  <CopyButton text={fullLink(p.reveal_url)} />
                </div>
                <code className="link-url">{fullLink(p.reveal_url)}</code>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
