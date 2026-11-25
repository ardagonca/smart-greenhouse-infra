import { API } from '../../api';
import React, { useState, useEffect } from 'react';
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine
} from 'recharts';
import { motion, useReducedMotion } from 'motion/react';
import './Analytics.css';

const RISK_THRESHOLD = 0.5; // olasılık skoru için görsel "yüksek risk" sınırı
const VPD_RISK_LIMIT = 0.8; // backend etiketleme kuralı: VPD < 0.8 kPa = yüksek nem riski
const AXIS = { stroke: '#64748b', tick: { fontSize: 12 }, tickLine: false };
const RANGES = [{ hours: 24, label: 'Son 24 saat', slug: '24-saat' }, { hours: 168, label: 'Son 7 gün', slug: '7-gun' }, { hours: 720, label: 'Son 30 gün', slug: '30-gun' }];

const fmt = (v) => (typeof v === 'number' ? v.toLocaleString('tr-TR', { maximumFractionDigits: 2 }) : v);
const fullTime = (t) => new Date(t).toLocaleString('tr-TR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });

function ChartTip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="an-tip">
      <b>{fullTime(row.time)} <span className="an-tz">(yerel saat)</span></b>
      {payload.map((e) => (
        <div key={e.name}>
          {e.name}: <strong>{fmt(e.value)}</strong>
          {e.dataKey === 'vpd' && typeof e.value === 'number' && e.value < VPD_RISK_LIMIT && <span className="an-tip-flag"> ▲ Yüksek nem riski</span>}
        </div>
      ))}
    </div>
  );
}

function LineBlock({ data, dataKey, name, stroke, width, limit, animate, domain = ['auto', 'auto'], limitLabel }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="#e2e8f0" />
        <XAxis dataKey="timeLabel" {...AXIS} minTickGap={32} />
        <YAxis {...AXIS} domain={domain} axisLine={false} />
        <Tooltip content={<ChartTip />} />
        {limit !== undefined && (
          <ReferenceLine y={limit} stroke="#475569" strokeDasharray="6 4" label={limitLabel && { value: limitLabel, position: 'insideBottomRight', fill: '#475569', fontSize: 12 }} />
        )}
        <Line type="monotone" dataKey={dataKey} name={name} stroke={stroke} strokeWidth={width} dot={false} activeDot={{ r: 5 }}
          isAnimationActive={animate} animationDuration={1000} animationEasing="ease-out" />
      </LineChart>
    </ResponsiveContainer>
  );
}

function downloadCsv(rows, slug) {
  const lines = ['zaman,sicaklik_c,nem,vpd_kpa,risk', ...rows.map(d => [d.time, d.temp, d.hum, d.vpd, d.risk].join(','))];
  const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = `gecmis-veri-${slug}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function Analytics() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [range, setRange] = useState(RANGES[0]);
  const [drawing, setDrawing] = useState(true); // çizgi çizimi yalnızca ilk yüklemede oynar
  const reduce = useReducedMotion();

  useEffect(() => {
    const ctrl = new AbortController(); // aralık değişince eski istek iptal edilir
    fetch(`${API}/api/analytics/historical?hours=${range.hours}`, { signal: ctrl.signal })
      .then(res => { if (!res.ok) throw new Error(res.status); return res.json(); })
      .then(json => {
        const rows = json.data || [];
        const first = rows.length ? Date.parse(rows[0].time) : 0;
        const last = rows.length ? Date.parse(rows[rows.length - 1].time) : 0;
        const opts = last - first > 36 * 60 * 60 * 1000
          ? { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }
          : { hour: '2-digit', minute: '2-digit' };
        setData(rows.map(d => ({ ...d, temp: d.temp == null ? null : (d.temp - 32) * 5 / 9, timeLabel: new Date(d.time).toLocaleString('tr-TR', opts) })));
        setFailed(false);
        setLoading(false);
      })
      .catch(err => {
        if (err.name === 'AbortError') return;
        console.error('Error fetching analytics', err);
        setData([]);
        setFailed(true);
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [range]);

  useEffect(() => {
    if (loading) return undefined;
    const t = setTimeout(() => setDrawing(false), 1300);
    return () => clearTimeout(t);
  }, [loading]);

  const pick = (r) => { if (r !== range) { setLoading(true); setRange(r); } };

  const risks = data.map(d => d.risk).filter(v => typeof v === 'number');
  const hasRisk = risks.length > 0; // geçmiş satırlarda yapay zekâ skoru yalnızca canlı telemetri geldiyse dolu olur
  const peak = hasRisk ? Math.max(...risks) : null;
  const vpds = data.map(d => d.vpd).filter(v => typeof v === 'number');
  const lowVpd = vpds.filter(v => v < VPD_RISK_LIMIT).length;
  const animate = drawing && !reduce;

  const container = { hidden: {}, show: { transition: { staggerChildren: reduce ? 0 : 0.1 } } };
  const item = { hidden: { opacity: reduce ? 1 : 0, y: reduce ? 0 : 12 }, show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: 'easeOut' } } };

  return (
    <main className="an">
      <div className="an-head">
        <div>
          <h2>Geçmiş veri analizi</h2>
          <p>Sera ölçümlerinin {range.label.toLowerCase()} içindeki seyri · saatler yerel saat (tarayıcı)</p>
        </div>
        <div className="an-tools">
            <div className="an-seg" role="group" aria-label="Zaman aralığı">
              {RANGES.map(r => (
                <button key={r.hours} type="button" aria-pressed={range === r} className={range === r ? 'on' : ''} onClick={() => pick(r)}>{r.label}</button>
              ))}
            </div>
            {data.length > 0 && <button type="button" className="an-btn" onClick={() => downloadCsv(data, range.slug)}>CSV olarak indir ({range.label.toLowerCase()})</button>}
        </div>
      </div>

      {loading ? (
        <div className="an-state" role="status"><strong>Geçmiş veriler yükleniyor</strong>Sunucudan ölçümler alınıyor, birkaç saniye sürebilir.</div>
      ) : failed ? (
        <div className="an-state"><strong>Sunucuya ulaşılamadı</strong>Arka uç ({API}) kapalı olabilir. Sunucuyu başlatıp aralığı yeniden seçin.</div>
      ) : data.length === 0 ? (
        <div className="an-state"><strong>{range.label} için kayıt yok</strong>Bu aralıkta sensör kaydı bulunmuyor olabilir. Daha geniş bir zaman aralığı seçin ya da sunucunun veri kaydettiğinden emin olun.</div>
      ) : (
        <motion.div className="an-body" variants={container} initial="hidden" animate="show">
          {hasRisk ? (
          <motion.section variants={item} className="an-hero" aria-labelledby="an-risk">
            <div className="an-hero-top">
              <div>
                <h3 id="an-risk">Hastalık riski skoru</h3>
                <p className="an-hero-sub">Her saatin en yüksek skoru (telemetri modeli, 0 ile 1 arası). Kesikli çizgi {fmt(RISK_THRESHOLD)} eşiğini gösterir.</p>
              </div>
              {peak !== null && (
                <div className="an-peak">
                  <div className="an-peak-val" style={{ color: peak >= RISK_THRESHOLD ? 'var(--bad)' : 'var(--text-main)' }}>{fmt(peak)}</div>
                  <div className="an-peak-lbl">{peak >= RISK_THRESHOLD ? '▲ Eşik aşıldı · ' : ''}dönemin en yüksek skoru</div>
                </div>
              )}
            </div>
            <div className="an-hero-chart" role="img" aria-label={`Risk skoru grafiği, dönemin en yüksek değeri ${fmt(peak)}`}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorRisk" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#ef4444" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="#ef4444" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="timeLabel" {...AXIS} minTickGap={32} />
                  <YAxis {...AXIS} domain={[0, 1]} axisLine={false} />
                  <Tooltip content={<ChartTip />} />
                  <ReferenceLine y={RISK_THRESHOLD} stroke="#b91c1c" strokeDasharray="6 4" label={{ value: 'Yüksek risk eşiği', position: 'insideTopRight', fill: '#b91c1c', fontSize: 12 }} />
                  <Area type="monotone" dataKey="risk" name="Risk skoru" stroke="#ef4444" strokeWidth={2.5} fill="url(#colorRisk)"
                    isAnimationActive={animate} animationDuration={1000} animationEasing="ease-out" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </motion.section>
          ) : (
          <motion.section variants={item} className="an-hero" aria-labelledby="an-vpd-hero">
            <div className="an-hero-top">
              <div>
                <h3 id="an-vpd-hero">Ortalama VPD (kPa)</h3>
                <p className="an-hero-sub">Saatlik ortalama buhar basıncı açığı. Kesikli çizgi {fmt(VPD_RISK_LIMIT)} kPa: bunun altı yüksek nem riski demektir.</p>
              </div>
              {vpds.length > 0 && (
                <div className="an-peak">
                  <div className="an-peak-val" style={{ color: lowVpd > 0 ? 'var(--bad)' : 'var(--text-main)' }}>{lowVpd}</div>
                  <div className="an-peak-lbl">{lowVpd > 0 ? '▲ ' : '✓ '}saat sınırın altında ({fmt(VPD_RISK_LIMIT)} kPa)</div>
                </div>
              )}
            </div>
            <div className="an-hero-chart" role="img" aria-label={`VPD grafiği, ${vpds.length} ölçümün ${lowVpd} tanesi ${fmt(VPD_RISK_LIMIT)} kPa sınırının altında`}>
              <LineBlock data={data} dataKey="vpd" name="VPD (kPa)" stroke="#15803d" width={2.5} limit={VPD_RISK_LIMIT} limitLabel="0,8 kPa sınırı" animate={animate} />
            </div>
          </motion.section>
          )}

          <motion.div variants={item} className="an-minor">
            <section aria-labelledby="an-temp">
              <h3 id="an-temp">Ortalama sıcaklık (°C)</h3>
              <p>Saatlik ortalama iç ortam sıcaklığı</p>
              <div className="an-minor-chart" role="img" aria-label="Ortalama sıcaklık grafiği, °C">
                <LineBlock data={data} dataKey="temp" name="Sıcaklık (°C)" stroke="#2563eb" width={2} animate={animate} />
              </div>
            </section>

            <section aria-labelledby="an-hum">
              <h3 id="an-hum">Ortalama nem (%)</h3>
              <p>Saatlik ortalama iç ortam bağıl nemi</p>
              <div className="an-minor-chart" role="img" aria-label="Ortalama nem grafiği, yüzde">
                <LineBlock data={data} dataKey="hum" name="Nem (%)" stroke="#0891b2" width={2} animate={animate} />
              </div>
            </section>

            {hasRisk && (
            <section aria-labelledby="an-vpd">
              <h3 id="an-vpd">Ortalama VPD (kPa)</h3>
              <p>Kesikli çizgi: {fmt(VPD_RISK_LIMIT)} kPa altı yüksek nem riski</p>
              <div className="an-minor-chart" role="img" aria-label="Ortalama VPD grafiği, kPa">
                <LineBlock data={data} dataKey="vpd" name="VPD (kPa)" stroke="#15803d" width={2} limit={VPD_RISK_LIMIT} animate={animate} />
              </div>
            </section>
            )}
          </motion.div>
        </motion.div>
      )}
    </main>
  );
}
