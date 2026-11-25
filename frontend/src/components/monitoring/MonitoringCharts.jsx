import { API } from '../../api';
import React, { useEffect, useRef, useState } from 'react';
import {
  ResponsiveContainer, BarChart, Bar, Cell, XAxis, YAxis, Tooltip, CartesianGrid,
  LineChart, Line, ComposedChart, Area, Legend,
} from 'recharts';
import { motion, useReducedMotion } from 'motion/react';
import { Reveal } from '../../motionKit';
import './MonitoringCharts.css';

// Gerçek veri: Grafana (verdify-tsdb) -> /api/monitoring/charts
// Okabe-Ito tabanlı, birbirinden belirgin tonlar (renk körlüğüne uygun)
const EQUIP = {
  heat1: { label: 'Isıtıcı 1', color: '#D55E00' },
  heat2: { label: 'Isıtıcı 2', color: '#E69F00' },
  fan1: { label: 'Fan 1', color: '#0072B2' },
  fan2: { label: 'Fan 2', color: '#56B4E9' },
  fog: { label: 'Sisleme', color: '#CC79A7' },
  vent: { label: 'Havalandırma', color: '#009E73' },
  grow_light_main: { label: 'Büyütme Işığı', color: '#F0E442' },
  drip_wall: { label: 'Damla (Duvar)', color: '#332288' },
  drip_center: { label: 'Damla (Merkez)', color: '#999999' },
};
// Açık tonlu (örn. sarı) çubuklar beyaz zeminde kaybolmasın diye ince koyu kenar
const EDGE = { stroke: '#0f172a', strokeOpacity: 0.55, strokeWidth: 0.6 };
const ZONES = { north: ['Kuzey', '#6366f1'], center: ['Merkez', '#f59e0b'], east: ['Doğu', '#10b981'], west: ['Batı', '#ec4899'] };
const AXIS = { fill: '#64748b', fontSize: 12 };
const LEGEND_STYLE = { fontSize: 12, color: '#475569', paddingTop: 8 };
const fmtK = (v) => v.toFixed(2).replace('.', ',');

// VPD bantları: <0.8 yüksek nem (küf riski), 0.8-1.2 hedef, >1.2 kuru
// Renk körlüğü için: koyu mavi / orta yeşil / açık sarı (parlaklıkları farklı) + lejantta yazı
const binColor = (v) => (v < 0.8 ? '#2563eb' : v < 1.2 ? '#10b981' : '#fcd34d');

// Isı haritası: viridis benzeri, tek yönlü parlaklık artışı (renk körlüğüne ve gri tonlamaya dayanıklı)
const STOPS = [[0.4, [68, 1, 84]], [0.8, [49, 104, 142]], [1.2, [53, 183, 121]], [1.8, [253, 231, 37]]];
function heatColor(v) {
  if (v <= STOPS[0][0]) return `rgb(${STOPS[0][1]})`;
  for (let i = 1; i < STOPS.length; i++) {
    if (v <= STOPS[i][0]) {
      const [a, ca] = STOPS[i - 1], [b, cb] = STOPS[i], t = (v - a) / (b - a);
      return `rgb(${ca.map((c, k) => Math.round(c + (cb[k] - c) * t)).join(',')})`;
    }
  }
  return `rgb(${STOPS[STOPS.length - 1][1]})`;
}

function Tip({ active, payload, label, unit = '', digits = 1, fmt }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="mc-tip">
      <div className="mc-tip-title">{fmt ? fmt(label) : label}</div>
      {payload.filter(p => p.value != null).map(p => (
        <div key={p.dataKey} className="mc-tip-row">
          <span className="mc-dot" style={{ background: p.color || p.fill }} />
          <span>{p.name}</span>
          <strong>{(Array.isArray(p.value) ? p.value : [p.value]).map(v => Number(v).toFixed(digits)).join('–')}{unit}</strong>
        </div>
      ))}
    </div>
  );
}

function Card({ title, sub, children, wide, right }) {
  return (
    <section className={`mc-card${wide ? ' mc-wide' : ''}`}>
      <header className="mc-card-head">
        <div>
          <h4>{title}</h4>
          <p>{sub}</p>
        </div>
        {right}
      </header>
      {children}
    </section>
  );
}

export default function MonitoringCharts() {
  const [days, setDays] = useState(7);
  const [d, setD] = useState(null);
  const [status, setStatus] = useState('loading'); // loading | ok | error | pending
  const [tick, setTick] = useState(0);
  const [sel, setSel] = useState(null);
  const tries = useRef(0);
  const reduce = useReducedMotion();
  const loading = status === 'loading';

  useEffect(() => {
    let live = true, timer;
    setStatus('loading');
    fetch(`${API}/api/monitoring/charts?days=${days}`)
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(j => {
        if (!live) return;
        if (j.data) { setD(j.data); setStatus('ok'); return; }
        // arşiv henüz alınmadı: 20 sn'de bir, en çok 5 kez yeniden dene
        setD(null); setStatus('pending');
        if (tries.current++ < 5) timer = setTimeout(() => setTick(t => t + 1), 20000);
      })
      .catch(() => { if (live) setStatus('error'); }); // eski veri silinmez
    return () => { live = false; clearTimeout(timer); };
  }, [days, tick]);

  const head = (
    <div className="mc-head">
      <div>
        <h3>Geçmiş grafikleri</h3>
        <p>Verdify genel panosu ve saatlik arşiv. Saatler Denver (Colorado) saatidir, tarayıcı saatinden farklı olabilir.</p>
      </div>
      <div className="mc-seg" role="group" aria-label="Zaman aralığı">
        {[7, 14, 30].map(n => (
          <button key={n} type="button" aria-pressed={days === n} onClick={() => { tries.current = 0; setDays(n); }}>{n} gün</button>
        ))}
      </div>
    </div>
  );

  if (!d) {
    const msg = status === 'error' ? 'Grafik verisi alınamadı. Yeniden denemek için gün aralığını değiştirin veya sayfayı yenileyin.'
      : status === 'pending' ? 'Veri henüz hazır değil (sunucu arşivi alıyor), birkaç dakika sonra yenilenir.'
        : 'Grafikler yükleniyor…';
    return (
      <section className="mc-wrap">
        {head}
        <div className={`mc-state${status === 'error' ? ' bad' : ''}`} role={status === 'error' ? 'alert' : 'status'}>{msg}</div>
      </section>
    );
  }

  const total = d.vpd_histogram.reduce((s, b) => s + b.hours, 0);
  const inTarget = d.vpd_histogram.filter(b => b.bin >= 0.8 && b.bin < 1.2).reduce((s, b) => s + b.hours, 0);
  const usedEquip = d.equipment.filter(e => d.runtime_daily.some(r => (r[e] || 0) > 0));
  const heatDays = [...new Set(d.vpd_heatmap.map(c => c.day))];
  const heatMap = new Map(d.vpd_heatmap.map(c => [`${c.day}-${c.hour}`, c.vpd]));

  return (
    <section className="mc-wrap">
      {head}
      {status === 'error' && <div className="mc-note" role="alert">Güncel veri alınamadı, son başarılı veri gösteriliyor.</div>}

      <motion.div className="mc-grid" aria-busy={loading} animate={{ opacity: loading ? 0.5 : 1 }} transition={{ duration: reduce ? 0 : 0.25 }}>
        <Card title="VPD Dağılımı" sub={`Son ${d.days} gün, saatlik ortalamalar (Denver saati) · hedef bandında %${total ? Math.round((inTarget / total) * 100) : 0}`}
          right={<div className="mc-legend"><span><i style={{ background: '#2563eb' }} />Nemli &lt;0,8</span><span><i style={{ background: '#10b981' }} />Hedef 0,8–1,2</span><span><i style={{ background: '#fcd34d' }} />Kuru &gt;1,2</span></div>}>
          <div className="mc-chart">
            <Reveal k={d.days}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={d.vpd_histogram} barCategoryGap="12%">
                  <CartesianGrid vertical={false} stroke="#eef2f7" />
                  <XAxis dataKey="bin" tick={AXIS} axisLine={false} tickLine={false} tickFormatter={v => v.toFixed(1)} />
                  <YAxis tick={AXIS} axisLine={false} tickLine={false} width={34} />
                  <Tooltip cursor={{ fill: 'rgba(148,163,184,0.12)' }} content={<Tip unit=" saat" digits={0} fmt={v => `VPD ${Number(v).toFixed(1)}–${(Number(v) + 0.1).toFixed(1)} kPa`} />} />
                  <Bar dataKey="hours" name="Süre" radius={[8, 8, 0, 0]} isAnimationActive={false} {...EDGE}>
                    {d.vpd_histogram.map(b => <Cell key={b.bin} fill={binColor(b.bin)} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Reveal>
          </div>
        </Card>

        <Card title="Ekipman Çalışma Süresi" sub={`Günlük toplam (dk) · son ${d.days} gün · Denver (Colorado) saati`}>
          <div className="mc-chart">
            <Reveal k={d.days}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={d.runtime_daily} barCategoryGap="22%">
                  <CartesianGrid vertical={false} stroke="#eef2f7" />
                  <XAxis dataKey="day" tick={AXIS} axisLine={false} tickLine={false} />
                  <YAxis tick={AXIS} axisLine={false} tickLine={false} width={40} />
                  <Tooltip cursor={{ fill: 'rgba(148,163,184,0.12)' }} content={<Tip unit=" dk" />} />
                  {usedEquip.map((e, k) => (
                    <Bar key={e} dataKey={e} name={EQUIP[e]?.label || e} stackId="a" fill={EQUIP[e]?.color || '#64748b'} {...EDGE}
                      radius={k === usedEquip.length - 1 ? [6, 6, 0, 0] : 0} isAnimationActive={false} />
                  ))}
                  <Legend iconType="circle" iconSize={8} wrapperStyle={LEGEND_STYLE} />
                </BarChart>
              </ResponsiveContainer>
            </Reveal>
          </div>
        </Card>

        <Card title="Bölge Sıcaklıkları" sub="Son 24 saat, saatlik ortalama (°C) · Denver (Colorado) saati">
          <div className="mc-chart">
            <Reveal k="zones">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={d.zones_24h}>
                  <CartesianGrid vertical={false} stroke="#eef2f7" />
                  <XAxis dataKey="time" tick={AXIS} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={28} />
                  <YAxis tick={AXIS} axisLine={false} tickLine={false} width={34} domain={['dataMin - 1', 'dataMax + 1']} tickFormatter={v => Math.round(v)} />
                  <Tooltip content={<Tip unit=" °C" />} />
                  {Object.entries(ZONES).map(([k, [label, color]]) => (
                    <Line key={k} type="monotone" dataKey={k} name={label} stroke={color} strokeWidth={2.5} dot={false} connectNulls isAnimationActive={false} />
                  ))}
                  <Legend iconType="circle" iconSize={8} wrapperStyle={LEGEND_STYLE} />
                </LineChart>
              </ResponsiveContainer>
            </Reveal>
          </div>
        </Card>

        <Card title="Sıcaklık ve Hedef Bandı" sub="Son 24 saat, saatlik ortalama (°C) · Denver (Colorado) saati · gölge: hedef aralığı">
          <div className="mc-chart">
            <Reveal k="band">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={d.zones_24h.map(r => ({ ...r, band: r.low != null && r.high != null ? [r.low, r.high] : null }))}>
                  <CartesianGrid vertical={false} stroke="#eef2f7" />
                  <XAxis dataKey="time" tick={AXIS} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={28} />
                  <YAxis tick={AXIS} axisLine={false} tickLine={false} width={34} domain={['auto', 'auto']} tickFormatter={v => Math.round(v)} />
                  <Tooltip content={<Tip unit=" °C" />} />
                  <Area type="monotone" dataKey="band" name="Hedef aralığı" stroke="none" fill="#34d399" fillOpacity={0.18} connectNulls isAnimationActive={false} />
                  <Line type="monotone" dataKey="avg" name="Ortalama sıcaklık" stroke="#f97316" strokeWidth={2.5} dot={false} connectNulls isAnimationActive={false} />
                  <Legend iconType="circle" iconSize={8} wrapperStyle={LEGEND_STYLE} />
                </ComposedChart>
              </ResponsiveContainer>
            </Reveal>
          </div>
        </Card>

        <Card wide title="VPD Isı Haritası" sub="Denver (Colorado) saati · saat × gün · ortalama VPD (kPa)"
          right={<div className="mc-scale"><span>0,4 (nemli)</span><i /><span>1,8 (kuru)</span></div>}>
          <div className="mc-heat" tabIndex={0} role="region" aria-label={`VPD ısı haritası, ${heatDays.length} gün, saatlik ortalama kPa, Denver saati. Koyu mor nemli, sarı kuru. Gün özetleri aşağıdaki tabloda.`}>
            <div className="mc-heat-hours" aria-hidden="true">
              <span />
              {Array.from({ length: 24 }, (_, h) => <span key={h}>{h % 3 === 0 ? String(h).padStart(2, '0') : ''}</span>)}
            </div>
            {heatDays.map((day) => (
              <div className="mc-heat-row" key={day} aria-hidden="true">
                <span className="mc-heat-day">{day}</span>
                {Array.from({ length: 24 }, (_, h) => {
                  const v = heatMap.get(`${day}-${h}`);
                  const txt = v == null ? `${day} saat ${h}: veri yok` : `${day} saat ${h}: ${fmtK(v)} kPa`;
                  return (
                    <i key={h} className={`mc-cell${sel === txt ? ' sel' : ''}`} title={txt} onClick={() => setSel(txt)}
                      style={v == null ? undefined : { background: heatColor(v) }} />
                  );
                })}
              </div>
            ))}
          </div>
          <p className="mc-heat-read" aria-live="polite">{sel || 'Değeri görmek için bir hücreye dokunun veya tıklayın.'}</p>
          <table className="mc-sr">
            <caption>VPD günlük özeti (Denver saati)</caption>
            <thead><tr><th>Gün</th><th>Ortalama VPD (kPa)</th><th>En kuru saat</th></tr></thead>
            <tbody>
              {heatDays.map(day => {
                const hs = Array.from({ length: 24 }, (_, h) => [h, heatMap.get(`${day}-${h}`)]).filter(([, v]) => v != null);
                if (!hs.length) return <tr key={day}><td>{day}</td><td>veri yok</td><td>veri yok</td></tr>;
                const dry = hs.reduce((a, b) => (b[1] > a[1] ? b : a));
                return <tr key={day}><td>{day}</td><td>{fmtK(hs.reduce((s, [, v]) => s + v, 0) / hs.length)}</td><td>saat {dry[0]}: {fmtK(dry[1])} kPa</td></tr>;
              })}
            </tbody>
          </table>
        </Card>
      </motion.div>
    </section>
  );
}
