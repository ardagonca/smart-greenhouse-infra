import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence, useReducedMotion } from 'motion/react';
import ModelComparison from '../monitoring/ModelComparison';
import './SystemHealth.css';

const API = 'http://localhost:8000';
const POLL_MS = 60000;

// Her bileşen: { state: 'ok'|'warn'|'bad', detail, since (Date|null), action }
async function getJson(path, signal) {
  const res = await fetch(API + path, { signal });
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}

function ageText(date, now) {
  if (!date || isNaN(date)) return null;
  const s = Math.max(0, Math.round((now - date) / 1000));
  if (s < 60) return 'az önce';
  const m = Math.round(s / 60);
  if (m < 60) return `${m} dk önce`;
  const h = s / 3600;
  if (h < 48) return `${h.toFixed(1).replace('.', ',')} saat önce`;
  return `${Math.round(h / 24)} gün önce`;
}

// "YYYY-MM-DD HH:MM:SS" America/Denver yerel saati -> gerçek an (tarayıcı saat dilimine bağlı değil)
const DENVER = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Denver', hourCycle: 'h23',
  year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric',
});
function denverOffset(t) {
  const p = Object.fromEntries(DENVER.formatToParts(new Date(t)).map((x) => [x.type, +x.value]));
  return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) - Math.floor(t / 1000) * 1000;
}
function denverToDate(str) {
  const m = String(str).match(/^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)(?::(\d\d))?/);
  if (!m) return null;
  const wall = Date.UTC(+m[1], m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0));
  return new Date(wall - denverOffset(wall - denverOffset(wall))); // ikinci geçiş: DST sınırı için
}

const STATE = {
  unk: { label: 'Bilinmiyor', icon: '?' },
  ok: { label: 'Çalışıyor', icon: '✓' },
  warn: { label: 'Dikkat', icon: '!' },
  bad: { label: 'Ulaşılamıyor', icon: '✕' },
  load: { label: 'Kontrol ediliyor', icon: '…' },
};

const API_DOWN = 'Backend kapalı olabilir. Docker\'ın çalıştığını kontrol edin: docker compose up -d';

async function probe(sensorAt) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 6000);
  const run = (path) => getJson(path, ctl.signal).then((v) => ({ v }), (e) => ({ e }));
  const [root, cond, scada, ml] = await Promise.all([
    run('/'), run('/api/conditions/latest'), run('/api/monitoring/scada'), run('/api/ml/predict_today'),
  ]);
  clearTimeout(timer);

  const r = {};
  r.api = root.e
    ? { state: 'bad', detail: 'API yanıt vermiyor.', action: API_DOWN }
    : { state: 'ok', detail: 'Backend yanıt veriyor (localhost:8000).' };

  const down = (what) => ({ state: 'bad', detail: `${what} alınamadı.`, action: root.e ? API_DOWN : 'Backend günlüklerine bakın; Verdify erişimi geçici olarak kesilmiş olabilir.' });

  // Verdify canlı ölçüm: ölçümün kendi zaman damgası
  if (cond.e) r.live = down('Canlı ölçüm');
  else if (!cond.v?.data) r.live = { state: 'bad', detail: 'Canlı ölçüm boş döndü.', action: 'Verdify kaynağı ve yerel arşiv şu an veri vermiyor.' };
  else {
    const t = new Date(cond.v.data.time);
    const h = (Date.now() - t) / 3600000;
    r.live = isNaN(t)
      ? { state: 'warn', detail: 'Ölçüm var ancak zaman bilgisi yok.' }
      : h > 6 ? { state: 'bad', detail: `Son ölçüm ${h.toFixed(1).replace('.', ',')} saat önce.`, since: t, action: 'Verdify sera sensörleri veya kaynak sitesi durmuş olabilir; arayüzdeki değerler eski.' }
      : h > 2 ? { state: 'warn', detail: 'Ölçümler gecikiyor.', since: t, action: 'Genellikle kısa süreli bir gecikmedir; bir süre sonra yenileyin.' }
      : { state: 'ok', detail: 'Verdify serasından taze ölçüm geliyor.', since: t };
  }

  // Saatlik arşiv (Monitoring sayfasının kaynağı)
  if (scada.e) r.archive = down('Saatlik arşiv');
  else if (!scada.v?.archive_hour) r.archive = { state: 'warn', detail: 'Arşiv henüz boş.', action: 'Arka plan senkronizasyonu çalışıyorsa birkaç dakika içinde dolar.' };
  else {
    const t = denverToDate(scada.v.archive_hour);
    const h = t ? (Date.now() - t) / 3600000 : NaN;
    const hs = h.toFixed(1).replace('.', ',');
    r.archive = isNaN(h)
      ? { state: 'warn', detail: 'Arşiv saati okunamadı.', action: 'Sunucu arşivi yenileyene kadar bekleyin; arayüzü açık tutun.' }
      : h > 24 ? { state: 'bad', detail: `Arşivdeki son tam saat ${hs} saat önce.`, since: t, sinceLabel: 'Arşiv saati', action: 'Arşiv günlerdir güncellenmemiş. Sunucu arşivi yenileyene kadar bekleyin ve arayüzü açık tutun.' }
      : h > 3 ? { state: 'warn', detail: `Arşivdeki son tam saat ${hs} saat önce.`, since: t, sinceLabel: 'Arşiv saati', action: 'Sunucu arşivi yenileyene kadar bekleyin; arayüzü açık tutun.' }
      : { state: 'ok', detail: `Arşivdeki son tam saat: ${String(scada.v.archive_hour).slice(0, 16)} (sera saati).`, since: t, sinceLabel: 'Arşiv saati' };
  }

  // Tahmin modeli
  if (ml.e) r.model = down('Tahmin modeli');
  else if (ml.v?.status && ml.v.status !== 'success') r.model = { state: 'bad', detail: ml.v.message || 'Model tahmin üretemedi.', action: 'Modeli eğitmek için: python -m app.ml.forecast' };
  else {
    const t = ml.v?.as_of ? new Date(ml.v.as_of) : null;
    const age = ml.v?.data_age_hours;
    r.model = age > 6
      ? { state: 'warn', detail: `Tahmin verisi ${String(age).replace('.', ',')} saat önce.`, since: t, action: 'Girdi verisi eskidiği için risk tahmini güncel durumu yansıtmayabilir.' }
      : { state: 'ok', detail: `Tahmin verisi ${age == null ? 'güncel' : String(age).replace('.', ',') + ' saat önce'}; 6 saatlik VPD tahmini üretiliyor.`, since: t, sinceLabel: 'Veri zamanı' };
  }

  // Arayüze akan canlı veri (App'in WebSocket + dakikalık yenilemesi)
  r.stream = sensorAt
    ? (Date.now() - sensorAt > 300000
        ? { state: 'warn', detail: 'Bu pencereye 5 dakikadır yeni veri gelmedi.', since: new Date(sensorAt), action: 'Sayfa dakikada bir kendini yeniler; sürerse uygulamayı yeniden başlatın.' }
        : { state: 'ok', detail: 'Arayüz canlı veri alıyor.', since: new Date(sensorAt), sinceLabel: 'Son alınan' })
    : { state: 'warn', detail: 'Bu oturumda henüz veri alınmadı.', action: root.e ? API_DOWN : 'Birkaç saniye bekleyin; gelmezse API durumunu kontrol edin.' };
  if (root.e) for (const k of ['live', 'archive', 'model', 'stream']) r[k] = { state: 'unk', detail: "API'ye ulaşılamadığı için durum bilinmiyor." };
  return r;
}

const ROWS = [
  ['api', 'API sunucusu'],
  ['live', 'Verdify canlı ölçüm'],
  ['archive', 'Saatlik arşiv'],
  ['model', 'Tahmin modeli'],
  ['stream', 'Arayüze veri akışı'],
];

export default function SystemHealth({ sensorData }) {
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [checkedAt, setCheckedAt] = useState(null);
  const [now, setNow] = useState(() => Date.now());
  const sensorAt = useRef(null);
  const running = useRef(false);
  const rm = useReducedMotion();
  const dy = rm ? 0 : 8;
  const dur = rm ? 0 : 0.22;

  useEffect(() => { if (sensorData) sensorAt.current = Date.now(); }, [sensorData]);

  const check = useCallback(async () => {
    if (running.current) return; // yoklama sürerken üst üste istek atma
    running.current = true;
    setBusy(true);
    try {
      const r = await probe(sensorAt.current);
      setRes(r); setCheckedAt(Date.now()); setNow(Date.now());
    } finally { running.current = false; setBusy(false); }
  }, []);

  useEffect(() => {
    check();
    const id = setInterval(() => { if (!document.hidden) check(); }, POLL_MS);
    return () => clearInterval(id);
  }, [check]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 15000);
    return () => clearInterval(id);
  }, []);

  const items = ROWS.map(([k, name]) => ({ k, name, ...(res?.[k] || { state: 'load' }) }));
  const bad = items.filter((i) => i.state === 'bad');
  const warn = items.filter((i) => i.state === 'warn');
  const overall = !res ? 'load' : bad.length ? 'bad' : warn.length ? 'warn' : 'ok';
  const parts = [];
  if (bad.length) parts.push(`${bad.length} bileşende sorun var`);
  if (warn.length) parts.push(`${warn.length} bileşende dikkat gerekiyor`);
  const title = { load: 'Sistem kontrol ediliyor', ok: 'Sistem sağlıklı' }[overall] || parts.join(', ');
  const apiDown = res?.api?.state === 'bad';
  const summary = apiDown ? 'API sunucusuna ulaşılamıyor; diğer bileşenlerin durumu da güvenilir değil. Önce arka ucu başlatın.' : {
    load: 'Bileşenler yoklanıyor.',
    ok: 'Tüm bileşenler yanıt veriyor ve veri güncel.',
    warn: 'Sistem çalışıyor ancak bazı veriler gecikmiş olabilir. Ayrıntılar aşağıda.',
    bad: 'Aşağıdaki kırmızı bileşenlere bakın; her birinin yanında ne yapılacağı yazıyor.',
  }[overall];

  return (
    <main className="sh">
      <header className={`sh-hero sh-${overall}`}>
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={overall} className="sh-badge" aria-hidden="true"
            initial={{ opacity: 0, scale: rm ? 1 : 0.7 }} animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0 }} transition={{ duration: dur }}
          >{STATE[overall]?.icon}</motion.span>
        </AnimatePresence>
        <div className="sh-hero-text" aria-live="polite" aria-atomic="true">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={overall}
              initial={{ opacity: 0, y: dy }} animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }} transition={{ duration: dur }}
            >
              <h2>{title}</h2>
              <p>{summary}</p>
            </motion.div>
          </AnimatePresence>
        </div>
        <div className="sh-hero-side">
          <button type="button" className="sh-btn" onClick={() => { if (!busy) check(); }} aria-disabled={busy} aria-busy={busy}>
            {busy && <span className="sh-spin" aria-hidden="true" />}
            {busy ? 'Kontrol ediliyor…' : 'Şimdi kontrol et'}
          </button>
          <span className="sh-muted">
            {checkedAt ? `Son kontrol: ${ageText(new Date(checkedAt), now)}` : 'Henüz kontrol edilmedi'}
          </span>
        </div>
      </header>

      <motion.section
        className="sh-list" aria-label="Bileşen durumları"
        initial="hidden" animate="show"
        variants={{ show: { transition: { staggerChildren: rm ? 0 : 0.06 } } }}
      >
        {items.map((i) => (
          <motion.article
            key={i.k} className={`sh-row sh-${i.state}`}
            variants={{ hidden: { opacity: 0, y: dy }, show: { opacity: 1, y: 0, transition: { duration: dur } } }}
          >
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={i.state} className="sh-status"
                initial={{ opacity: 0, y: dy }} animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }} transition={{ duration: dur }}
              >
                <span className="sh-dot" aria-hidden="true">{STATE[i.state].icon}</span>
                <span>{STATE[i.state].label}</span>
              </motion.div>
            </AnimatePresence>
            <div className="sh-body">
              <h3>{i.name}</h3>
              <p>{i.detail || 'Yanıt bekleniyor.'}</p>
              {i.action && <p className="sh-action"><strong>Ne yapmalı:</strong> {i.action}</p>}
            </div>
            <div className="sh-when">
              {i.since && !isNaN(i.since) ? (
                <>
                  <span className="sh-when-v">{ageText(i.since, now)}</span>
                  <span className="sh-muted">{i.sinceLabel || 'Son veri'}</span>
                </>
              ) : <span className="sh-muted">Zaman bilgisi yok</span>}
            </div>
          </motion.article>
        ))}
      </motion.section>

      <ModelComparison />

      <p className="sh-note sh-muted">
        Veri kaynağı: Verdify (Colorado) seranın herkese açık verisi; yaklaşık saatlik arşive kaydedilir.
        Sayfa her 60 saniyede bir kendini yeniler (sekme gizliyken durur).
      </p>
    </main>
  );
}
