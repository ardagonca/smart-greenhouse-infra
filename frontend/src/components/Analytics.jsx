import React, { useState, useEffect } from 'react';
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts';

export default function Analytics() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  
  useEffect(() => {
    fetch('http://localhost:8000/api/analytics/historical')
      .then(res => res.json())
      .then(json => {
        const formattedData = (json.data || []).map(d => ({
          ...d,
          timeLabel: new Date(d.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        }));
        setData(formattedData);
        setLoading(false);
      })
      .catch(err => {
        console.error('Error fetching analytics', err);
        setLoading(false);
      });
  }, []);

  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      return (
        <div style={{ background: 'rgba(255, 255, 255, 0.9)', padding: '12px', border: '1px solid #e2e8f0', borderRadius: '8px', boxShadow: '0 4px 6px rgba(0,0,0,0.1)' }}>
          <p style={{ margin: 0, fontWeight: 'bold' }}>{label}</p>
          {payload.map((entry, index) => (
            <p key={index} style={{ margin: 0, color: entry.color }}>
              {entry.name}: {entry.value?.toFixed(4) || entry.value}
            </p>
          ))}
        </div>
      );
    }
    return null;
  };

  return (
    <main style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '24px', overflowY: 'auto', padding: '12px 0' }}>
      <div className="panel glass-panel" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h2>AI Analytics Dashboard</h2>
          <p style={{ color: 'var(--text-muted)' }}>Historical Data & Predictive AI Risk Modeling</p>
        </div>
        <div style={{ display: 'flex', gap: '12px' }}>
          <button style={{ padding: '10px 16px', background: '#0f172a', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer' }}>
            Export CSV
          </button>
        </div>
      </div>
      
      {loading ? (
        // --- LOADING HISTORICAL DATA ---
        <div className="panel glass-panel" style={{ textAlign: 'center', padding: '48px', color: 'var(--text-muted)' }}>
          Loading historical data...
        </div>
      ) : data.length === 0 ? (
        // --- NO DATA ---
        <div className="panel glass-panel" style={{ textAlign: 'center', padding: '48px', color: 'var(--text-muted)' }}>
          No historical data available yet.
        </div>
      ) : (
        // --- HISTORICAL DATA DASHBOARD ---
        <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '24px' }}>
          <div className="panel glass-panel">
            <h3 style={{ marginBottom: '16px' }}>AI Disease Risk Score (Area)</h3>
            <div style={{ height: '300px' }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data}>
                  <defs>
                    <linearGradient id="colorRisk" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#ef4444" stopOpacity={0.8}/>
                      <stop offset="95%" stopColor="#ef4444" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="timeLabel" stroke="#94a3b8" />
                  <YAxis stroke="#94a3b8" />
                  <Tooltip content={<CustomTooltip />} />
                  <Area type="monotone" dataKey="risk" name="AI Risk Score" stroke="#ef4444" fillOpacity={1} fill="url(#colorRisk)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
            <div className="panel glass-panel">
              <h3 style={{ marginBottom: '16px' }}>Avg Temperature (°F)</h3>
              <div style={{ height: '300px' }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                    <XAxis dataKey="timeLabel" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" domain={['auto', 'auto']} />
                    <Tooltip content={<CustomTooltip />} />
                    <Line type="monotone" dataKey="temp" name="Temp (F)" stroke="#3b82f6" strokeWidth={3} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="panel glass-panel">
              <h3 style={{ marginBottom: '16px' }}>Avg VPD (kPa)</h3>
              <div style={{ height: '300px' }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                    <XAxis dataKey="timeLabel" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" domain={['auto', 'auto']} />
                    <Tooltip content={<CustomTooltip />} />
                    <Line type="monotone" dataKey="vpd" name="VPD (kPa)" stroke="#10b981" strokeWidth={3} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
