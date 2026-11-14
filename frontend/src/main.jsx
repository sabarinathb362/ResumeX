import React from 'react';
import ReactDOM from 'react-dom/client';
import '@fontsource-variable/inter';
import '@fontsource-variable/jetbrains-mono';
import '@fontsource-variable/source-serif-4';
import './index.css';
import './editor.css';         // shared panel styles too (ed-*, ats2-*, ig-*, ia-*), so not left to the lazy editor chunk
import './theme.css';          // after index.css: its tokens (light and dark) override the old palette
import App from './App.jsx';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
