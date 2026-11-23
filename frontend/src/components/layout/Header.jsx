import React, { useState, useEffect, useRef } from 'react';

const API = 'http://localhost:8000/api/profile';

export default function Header({ activeTab, onTabChange }) {
  const [profile, setProfile] = useState({ name: 'Arda', email: null, role: 'Admin' });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: '', email: '' });
  const [msg, setMsg] = useState(null);
  const box = useRef(null);

  useEffect(() => {
    fetch(API).then(r => r.json()).then(j => j.data && setProfile(j.data)).catch(() => {}); // backend kapalıysa varsayılan kalır
  }, []);

  useEffect(() => { // dışarı tıklayınca kapan
    if (!open) return;
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const toggle = () => {
    setForm({ name: profile.name, email: profile.email || '' });
    setMsg(null);
    setOpen(o => !o);
  };

  const save = async (e) => {
    e.preventDefault();
    try {
      const res = await fetch(API, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: form.name.trim(), email: form.email.trim() || null }) });
      if (!res.ok) throw new Error();
      setProfile((await res.json()).data);
      setMsg({ ok: true, text: 'Kaydedildi' });
    } catch {
      setMsg({ ok: false, text: 'Kaydedilemedi: ad 1-50 karakter, e-posta geçerli olmalı' });
    }
  };

  const field = { width: '100%', padding: '8px 10px', border: '1px solid #e2e8f0', borderRadius: '8px', fontSize: '0.85rem', boxSizing: 'border-box' };

  return (
    <header>
      <div className="logo" style={{display: 'flex', alignItems: 'center', gap: '10px'}}>
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
        </svg>
        <span>Verdify</span>
      </div>
      
      <div className="nav-tabs">
        {['Overview', 'Weather', 'Analytics', 'Monitoring', 'System Health'].map(tab => (
          <div 
            key={tab} 
            className={`nav-tab ${activeTab === tab ? 'active' : ''}`}
            onClick={() => onTabChange(tab)}
            style={{cursor: 'pointer'}}
          >
            {tab}
          </div>
        ))}
      </div>

      <div className="nav-right" style={{display: 'flex', gap: '16px', alignItems: 'center'}}>
        <button style={{background: 'white', border: 'none', padding: '10px', borderRadius: '50%', cursor: 'pointer', boxShadow: '0 2px 10px rgba(0,0,0,0.02)'}}>
          🔔
        </button>
        <div ref={box} style={{position: 'relative'}}>
          <div className="user-profile" onClick={toggle} style={{cursor: 'pointer'}} role="button" aria-expanded={open}>
            <div className="avatar">{profile.name.charAt(0).toUpperCase()}</div>
            <div style={{display: 'flex', flexDirection: 'column'}}>
              <span>{profile.name}</span>
              <span style={{fontSize: '0.75rem', color: 'var(--text-muted)'}}>{profile.role}</span>
            </div>
            <span>▼</span>
          </div>
          {open && (
            <form onSubmit={save} style={{position: 'absolute', right: 0, top: 'calc(100% + 8px)', width: '260px', zIndex: 50, background: 'white',
              borderRadius: '16px', boxShadow: '0 10px 30px rgba(0,0,0,0.12)', padding: '16px', display: 'flex', flexDirection: 'column', gap: '10px'}}>
              <label style={{fontSize: '0.75rem', color: 'var(--text-muted)'}}>Ad
                <input style={field} value={form.name} maxLength={50} required onChange={e => setForm({ ...form, name: e.target.value })} />
              </label>
              <label style={{fontSize: '0.75rem', color: 'var(--text-muted)'}}>E-posta
                <input style={field} type="email" value={form.email} maxLength={120} onChange={e => setForm({ ...form, email: e.target.value })} />
              </label>
              <div style={{fontSize: '0.75rem', color: 'var(--text-muted)'}}>Rol: {profile.role}</div>
              {msg && <div style={{fontSize: '0.75rem', color: msg.ok ? '#059669' : '#dc2626'}}>{msg.text}</div>}
              <button type="submit" style={{padding: '8px', border: 'none', borderRadius: '8px', background: 'var(--accent-blue)', color: 'white', fontWeight: 600, cursor: 'pointer'}}>Kaydet</button>
            </form>
          )}
        </div>
      </div>
    </header>
  );
}
