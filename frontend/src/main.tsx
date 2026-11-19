import { createRoot } from 'react-dom/client';
import { App } from './App';
import './global.css';

// No StrictMode: its double-mount would log session_start twice.
createRoot(document.getElementById('root')!).render(<App />);
