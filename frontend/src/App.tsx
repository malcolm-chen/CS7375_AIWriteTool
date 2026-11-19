import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { SessionPage } from './pages/SessionPage';
import { AdminPage } from './pages/AdminPage';
import { DemoPage } from './pages/DemoPage';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/session/:id" element={<SessionPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/demo" element={<DemoPage />} />
        <Route path="*" element={<Navigate to="/admin" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
