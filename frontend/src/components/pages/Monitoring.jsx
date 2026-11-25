import { API } from '../../api';
import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence, animate, useReducedMotion } from 'motion/react';
import MonitoringCharts from '../monitoring/MonitoringCharts';
import LiveCameras from '../monitoring/LiveCameras';
import LeafCheck from '../monitoring/LeafCheck';
import { Spark, RuntimeBar, VpdBullet } from '../monitoring/MonitoringViz';
import './Monitoring.css';

const MARK = { ok: '✓', warn: '!', bad: '✕' };

// Renk + ikon + metin birlikte (renk körlüğü)
// Değer değişince sayı akıcı geçer (yalnızca metin güncellenir, düzen oynamaz)
function CountUp({ value, decimals = 0 }) {
  const ref = useRef(null);
  const prev = useRef(null);
  const reduce = useReducedMotion();
  const fmt = (n) => n.toLocaleString('tr-TR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  const ok = typeof value === 'number' && Number.isFinite(value);
  const first = useRef(ok ? fmt(value) : '--'); // React metni bir daha yazmasın: değişimi yalnızca animasyon yönetir
  useEffect(() => {
    if (!ok || !ref.current) { prev.current = null; if (ref.current) ref.current.textContent = '--'; return; }
    const el = ref.current;
    if (reduce || prev.current == null) { el.textContent = fmt(value); prev.current = value; return; }
    el.textContent = fmt(prev.current);
    const c = animate(prev.current, value, { duration: 0.6, ease: 'easeOut', onUpdate: (v) => { el.textContent = fmt(v); } });
    prev.current = value;
    return () => c.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, ok, reduce]);
  return <span ref={ref}>{first.current}</span>;
}

// Durum değişince rozet kısa süre belirir (ilk yüklemede animasyon yok)
function Swap({ k, children, className }) {
  const reduce = useReducedMotion();
  return (
    <AnimatePresence initial={false} mode="wait">
      <motion.span key={k} className={className} style={{ display: 'inline-block' }} initial={{ opacity: 0, scale: reduce ? 1 : 0.9 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduce ? 0 : 0.18 }}>{children}</motion.span>
    </AnimatePresence>
  );
}

function State({ level, children }) {
  if (!level) return <span className="mn-state"><i aria-hidden="true">–</i>{children}</span>;
  return <span className={`mn-state ${level}`}><i aria-hidden="true">{MARK[level]}</i>{children}</span>;
}

const ACT_LABEL = { RUNNING: 'Çalışıyor', IDLE: 'Boşta', STANDBY: 'Hazırda', UNKNOWN: 'Bilinmiyor (veri yok)', OPEN: 'Açık', CLOSED: 'Kapalı', ACTIVE: 'Etkin' };
const CATS = [['all', 'Tümü'], ['heating', 'Isıtma'], ['lighting', 'Aydınlatma'], ['irrigation', 'Sulama'], ['ventilation', 'Havalandırma'], ['humidity', 'Nem']];
function ActPill({ status }) {
  const on = status === 'RUNNING' || status === 'ACTIVE';
  const cls = on ? ' on' : status === 'OPEN' ? ' open' : !(status in ACT_LABEL) || status === 'UNKNOWN' ? ' unk' : '';
  const mark = on ? '●' : cls === ' unk' ? '?' : '○';
  return <Swap k={status} className={`mn-pill${cls}`}><span aria-hidden="true">{mark}</span> {ACT_LABEL[status] || 'Bilinmiyor (veri yok)'}</Swap>;
}
const hhmm = (d) => d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });

export default function Monitoring({ active = true }) {
  const [scadaData, setScadaData] = useState(null);
  const [lastOk, setLastOk] = useState(null); // son başarılı SCADA yanıtı
  const [down, setDown] = useState(false);
  const [filterCategory, setFilterCategory] = useState('all');
  const [kpi, setKpi] = useState([]); // yalnızca grafik çizgileri: saatlik seriler
  const [activeModalActuator, setActiveModalActuator] = useState(null);
  const dlgRef = useRef(null);
  const openerRef = useRef(null);

  const fetchKpi = async () => {
    try {
      const r = await fetch(`${API}/api/monitoring/kpi`);
      if (r.ok) setKpi((await r.json()).data || []);
    } catch { /* önceki seri kalır */ }
  };
  const fetchScada = async () => {
    try {
      const res = await fetch(`${API}/api/monitoring/scada`);
      if (!res.ok) throw new Error(res.status);
      setScadaData(await res.json());
      setLastOk(new Date());
      setDown(false);
    } catch (err) {
      console.error('SCADA fetch error:', err);
      setDown(true);
    }
  };

  // Sekme gizliyken hiçbir periyodik istek atılmaz; açılınca hemen yenilenir
  useEffect(() => {
    if (!active) return;
    fetchScada(); fetchKpi();
    const a = setInterval(fetchScada, 15000);
    const b = setInterval(fetchKpi, 60000);
    return () => { clearInterval(a); clearInterval(b); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  // Ayrıntı penceresi: odak hapsi, Escape, kapanınca odağı açana geri ver
  useEffect(() => {
    if (!activeModalActuator) return;
    const opener = openerRef.current;
    const onKey = (e) => {
      if (e.key === 'Escape') return setActiveModalActuator(null);
      if (e.key !== 'Tab' || !dlgRef.current) return;
      const f = [...dlgRef.current.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')];
      if (!f.length) return e.preventDefault();
      const first = f[0], last = f[f.length - 1], cur = document.activeElement;
      if (!dlgRef.current.contains(cur)) { e.preventDefault(); first.focus(); }
      else if (e.shiftKey && cur === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && cur === last) { e.preventDefault(); first.focus(); }
    };
    window.addEventListener('keydown', onKey);
    return () => { window.removeEventListener('keydown', onKey); opener?.focus?.(); };
  }, [activeModalActuator]);

  const facility = scadaData?.facility || {};
  const actuators = scadaData?.actuators || [];
  const zones = scadaData?.zones || [];
  const allLogs = scadaData?.logs || [];

  const center = zones.find(z => z.id === 'center');
  const liveTemp = center?.temperature_c ?? null;
  const target = facility.temp_target_c ?? null;
  const dewC = facility.dew_point_c ?? null;
  const tempDelta = liveTemp != null && target != null ? liveTemp - target : null;
  const dewMargin = liveTemp != null && dewC != null ? liveTemp - dewC : null; // büyük sayı ve marj aynı anlık kaynaktan
  const updatedText = down ? (lastOk ? `Bağlantı yok, son veri ${hhmm(lastOk)}` : 'Veri alınamadı') : lastOk ? hhmm(lastOk) : '--';

  const filteredActuators = filterCategory === 'all' ? actuators : actuators.filter(a => a.category === filterCategory);
  const isOn = (s) => s === 'RUNNING' || s === 'ACTIVE' || s === 'OPEN';
  const runningCount = actuators.filter(a => isOn(a.status)).length;

  // Anlık durum düzeyleri
  const vpd = facility.vpd_kpa;
  const vpdLevel = vpd == null ? null : vpd >= 0.8 && vpd <= 1.2 ? 'ok' : 'warn';
  const tempLevel = tempDelta == null ? null : Math.abs(tempDelta) < 1 ? 'ok' : 'warn';
  const dewLevel = dewMargin == null ? null : dewMargin < 2 ? 'bad' : dewMargin < 4 ? 'warn' : 'ok';
  const known = [vpdLevel, tempLevel, dewLevel].filter(Boolean);
  const nBad = known.filter(l => l === 'bad').length;
  const nWarn = known.filter(l => l === 'warn').length;
  const missing = 3 - known.length; // hedefi/ölçümü olmayan göstergeler hüküm dışı kalır
  const tail = missing ? ` ${missing} gösterge için veri veya hedef yok.` : '';
  const verdict = !known.length ? ['', 'Veri bekleniyor', 'Anlık ölçümler henüz alınamadı.']
    : nBad ? ['bad', 'Kontrol önerilir', 'Kondensasyon riski yüksek olabilir, değerleri kontrol edin.' + tail]
    : nWarn ? ['warn', `${nWarn} değer hedefin dışında`, (known.length - nWarn ? 'Diğer ölçümler hedef aralığında.' : 'Ölçülen değerlerin hepsi hedef dışında.') + tail]
    : ['ok', missing ? 'Ölçülen değerler hedefte' : 'Sera hedef aralığında', (missing ? 'Hüküm yalnızca mevcut ölçümlere dayanıyor.' : 'VPD, sıcaklık ve çiy noktası marjı normal.') + tail];
  const reduce = useReducedMotion();
  // Sayfa yüklenirken tek sıralı giriş: şerit -> paneller
  const enter = (i) => reduce ? {} : { initial: { opacity: 0, y: 12 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.35, delay: i * 0.08, ease: 'easeOut' } };

  return (
    <main className="mn">
      <div className="mn-top">
        <div>
          <h2>Sera İzleme</h2>
          <p className="mn-sub">Verdify serası canlı telemetrisi: anlık durum, ekipmanlar, bölgeler ve geçmiş.</p>
        </div>
        <button className={`mn-refresh${down ? ' off' : ''}`} onClick={() => { fetchScada(); fetchKpi(); }}>
          ↻ Yenile <span>{updatedText}</span>
        </button>
      </div>

      <motion.section className="mn-strip" aria-label="Anlık durum" {...enter(0)}>
        <div className={`mn-verdict ${verdict[0]}`} role="status">
          <Swap k={verdict[0]} className="mn-verdict-mark"><span aria-hidden="true">{MARK[verdict[0]] || '…'}</span></Swap>
          <div><strong>{verdict[1]}</strong><span className="d">{verdict[2]}</span><span className="d mn-rule">Eşikler yaklaşık kuraldır, sera için ayarlanabilir (yalnızca VPD 0,8 kPa alt sınırı modelden gelir).</span></div>
        </div>
        <div className="mn-readings">
          <div className="mn-reading">
            <h3>Ortalama VPD</h3>
            <div className="mn-val"><b><CountUp value={vpd} decimals={2} /></b><span>kPa</span></div>
            <State level={vpdLevel}>{vpd == null ? 'Veri yok' : vpd < 0.8 ? 'Düşük, ortam nemli' : vpd <= 1.2 ? 'Hedef bandında (0,8–1,2)' : 'Yüksek, ortam kuru'}</State>
            <Spark data={kpi} k="vpd" color="#0369a1" gid="kpiVpd" />
          </div>
          <div className="mn-reading">
            <h3>Sıcaklık <small>(anlık, merkez)</small></h3>
            <div className="mn-val"><b><CountUp value={liveTemp} decimals={1} /></b><span>°C</span></div>
            <State level={tempLevel}>{tempDelta == null ? 'Veri yok' : `Hedef ${target} °C, fark ${tempDelta > 0 ? '+' : ''}${tempDelta.toFixed(1)}`}</State>
            <Spark data={kpi} k="temp" color="#0369a1" k2="target" color2="#94a3b8" gid="kpiTemp" />
          </div>
          <div className="mn-reading">
            <h3>Çiy noktası <small>(anlık)</small></h3>
            <div className="mn-val"><b><CountUp value={dewC} decimals={1} /></b><span>°C</span></div>
            <State level={dewLevel}>{dewMargin == null ? 'Veri yok' : `Kondensasyon riski ${dewMargin < 2 ? 'yüksek' : dewMargin < 4 ? 'orta' : 'düşük'}, marj ${dewMargin.toFixed(1)} °C`}</State>
            <Spark data={kpi} k="dew" color="#0369a1" k2="temp" color2="#94a3b8" gid="kpiDew" />
          </div>
          <div className="mn-reading">
            <h3>Güneş ışınımı</h3>
            <div className="mn-val"><b><CountUp value={facility.solar_irradiance_w_m2} decimals={0} /></b><span>W/m²</span></div>
            <span className="mn-note">Dış ortam ölçümü, hedefi yok</span>
            <Spark data={kpi} k="solar" color="#b45309" gid="kpiSolar" />
          </div>
        </div>
      </motion.section>

      <LiveCameras active={active} />
      <LeafCheck />

      <motion.div className="mn-two" {...enter(1)}>
        <section className="mn-panel" aria-labelledby="mn-act-h">
          <div className="mn-sec-head">
            <div>
              <h3 id="mn-act-h">Aktüatörler ve saha ekipmanı</h3>
              <p className="mn-sub">{actuators.length ? `${actuators.length} ekipmandan ${runningCount} tanesi açık veya çalışıyor. ` : ''}Durum son arşiv saatine göre, süreler son 24 saat toplamıdır.</p>
            </div>
            <div className="mn-seg" role="group" aria-label="Kategori filtresi">
              {CATS.map(([id, label]) => (
                <button key={id} aria-pressed={filterCategory === id} onClick={() => setFilterCategory(id)}>{label}</button>
              ))}
            </div>
          </div>
          <div>
            {!filteredActuators.length && <p className="mn-empty">{actuators.length ? 'Bu kategoride ekipman yok.' : 'Ekipman verisi bekleniyor.'}</p>}
            {filteredActuators.map((act) => (
              <div className="mn-act" key={act.id}>
                <h4>{act.name}</h4>
                <div className="mn-act-side">
                  <ActPill status={act.status} />
                  <button className="mn-link" onClick={(e) => { openerRef.current = e.currentTarget; setActiveModalActuator(act); }} aria-label={`${act.name} ayrıntıları`}>Ayrıntı</button>
                </div>
                <p>{act.description}</p>
                <div className="mn-rt">Son 24 saat: {act.runtime_min == null ? '--' : `${act.runtime_min} dk (${(act.runtime_min / 60).toFixed(1)} sa)`}</div>
                <RuntimeBar minutes={act.runtime_min} running={isOn(act.status)} />
              </div>
            ))}
          </div>
        </section>

        <section className="mn-panel" aria-labelledby="mn-zone-h">
          <div>
            <h3 id="mn-zone-h">Bölgesel iklim</h3>
            <p className="mn-sub">Bölge bazında sıcaklık, nem ve VPD, hedefle karşılaştırmalı.</p>
          </div>
          <div>
            {!zones.length && <p className="mn-empty">Bölge verisi bekleniyor.</p>}
            {zones.map((zone) => {
              const v = zone.vpd_kpa;
              const target = zone.vpd_target;
              const diff = v != null && target != null ? v - target : null;
              const lvl = diff == null ? null : Math.abs(diff) < 0.2 ? 'ok' : 'warn';
              return (
                <div className="mn-zone" key={zone.id}>
                  <div className="mn-zone-head">
                    <h4>{zone.name}</h4>
                    <State level={lvl}>{lvl == null ? 'Veri yok' : lvl === 'ok' ? 'Hedefte' : 'Sapma var'}</State>
                  </div>
                  <div className="mn-zone-vals">
                    <span>Sıcaklık<b>{zone.temperature_c ?? '--'} °C</b></span>
                    <span>Bağıl nem<b>%{zone.humidity_pct ?? '--'}</b></span>
                    <span>VPD<b>{v ?? '--'} kPa</b></span>
                  </div>
                  <VpdBullet value={typeof v === 'number' ? v : null} target={target ?? null} />
                  <div className="mn-zone-foot">Hedef {target ?? '--'} kPa · sapma {diff == null ? '--' : `${diff > 0 ? '+' : ''}${diff.toFixed(2)}`} kPa</div>
                </div>
              );
            })}
          </div>
        </section>
      </motion.div>

      <MonitoringCharts />

      <section className="mn-panel" aria-labelledby="mn-log-h">
        <div>
          <h3 id="mn-log-h">Saatlik çalışma kayıtları</h3>
          <p className="mn-sub">Her satır bir saatte kaç dakika çalışıldığını gösterir, {allLogs.length} kayıt.</p>
        </div>
        {!allLogs.length && <p className="mn-empty">Henüz kayıt yok.</p>}
        <ul className="mn-log">
          {allLogs.map((log, idx) => (
            <li key={idx}>
              <span className="g" title="Bilgi" aria-label="Bilgi">•</span>
              <time>{log.time}</time>
              <span className="t">{log.type}</span>
              <span className="m">{log.message}</span>
            </li>
          ))}
        </ul>
      </section>

      <AnimatePresence>
      {activeModalActuator && (
        <motion.div key="dlg" className="mn-modal" onClick={(e) => e.target === e.currentTarget && setActiveModalActuator(null)}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduce ? 0 : 0.18 }}>
          <motion.div ref={dlgRef} className="mn-dialog" role="dialog" aria-modal="true" aria-labelledby="mn-dlg-h"
            initial={{ opacity: 0, y: reduce ? 0 : 16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: reduce ? 0 : 8 }} transition={{ duration: reduce ? 0 : 0.2, ease: 'easeOut' }}>
            <header>
              <h3 id="mn-dlg-h">{activeModalActuator.name}</h3>
              <button className="mn-x" onClick={() => setActiveModalActuator(null)} aria-label="Kapat" autoFocus>✕</button>
            </header>
            <p className="mn-sub">{activeModalActuator.description}</p>
            <dl className="mn-dl">
              <dt>Mevcut durum</dt><dd><ActPill status={activeModalActuator.status} /></dd>
              <dt>Son 24 saat çalışma</dt><dd>{activeModalActuator.runtime_min ?? '--'} dk</dd>
              <dt>Veri kaynağı</dt><dd>Verdify Grafana (HTTP)</dd>
            </dl>
          </motion.div>
        </motion.div>
      )}
      </AnimatePresence>
    </main>
  );
}
