import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import CreateMenuPage from './pages/CreateMenuPage'
import MenuProgressPage from './pages/MenuProgressPage'

export default function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<CreateMenuPage />} />
        <Route path="/menu-progress" element={<MenuProgressPage />} />
      </Routes>
    </Router>
  )
}