// 后端 API 封装。组织者令牌通过 X-Organizer-Token 头传递。
async function request(path, { method = 'GET', body, organizerToken } = {}) {
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (organizerToken) headers['X-Organizer-Token'] = organizerToken

  const res = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  const text = await res.text()
  let data = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }
  if (!res.ok) {
    const detail = data && data.detail ? data.detail : `请求失败（${res.status}）`
    throw new Error(detail)
  }
  return data
}

export const createEvent = (payload) => request('/api/events', { method: 'POST', body: payload })
export const getEvent = (id, token) => request(`/api/events/${id}`, { organizerToken: token })
export const addParticipant = (id, token, name) =>
  request(`/api/events/${id}/participants`, { method: 'POST', body: { name }, organizerToken: token })
export const deleteParticipant = (id, token, participantId) =>
  request(`/api/events/${id}/participants/${participantId}`, { method: 'DELETE', organizerToken: token })
export const setForbiddenPairs = (id, token, pairs) =>
  request(`/api/events/${id}/forbidden-pairs`, { method: 'PUT', body: { pairs }, organizerToken: token })
export const drawEvent = (id, token) =>
  request(`/api/events/${id}/draw`, { method: 'POST', organizerToken: token })
export const getReveal = (revealToken) => request(`/api/reveal/${revealToken}`)
export const postReveal = (revealToken) => request(`/api/reveal/${revealToken}`, { method: 'POST' })
