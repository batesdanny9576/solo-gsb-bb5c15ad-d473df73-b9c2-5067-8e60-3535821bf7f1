import { Link, Route, Routes } from 'react-router-dom'
import HomePage from './pages/HomePage.jsx'
import EventPage from './pages/EventPage.jsx'
import RevealPage from './pages/RevealPage.jsx'

export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">🎁 秘密赠礼抽签</Link>
      </header>
      <main className="container">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/event/:id" element={<EventPage />} />
          <Route path="/reveal/:token" element={<RevealPage />} />
        </Routes>
      </main>
      <footer className="footer">每人恰好送出与收到一份礼物 · 一次性揭晓链接</footer>
    </div>
  )
}
