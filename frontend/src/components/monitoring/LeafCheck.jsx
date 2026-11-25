import { API } from '../../api';
import React, { useState, useEffect } from 'react';
import './LeafCheck.css';

const pct = (p) => `%${(p * 100).toFixed(1).replace('.', ',')}`;

export default function LeafCheck() {
  const [prev, setPrev] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [r, setR] = useState(null);

  // Önizleme nesne adresi bellekte kalmasın
  useEffect(() => () => prev && URL.revokeObjectURL(prev), [prev]);

  const pick = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    e.target.value = ''; // aynı dosya yeniden seçilince de onChange tetiklensin
    setPrev(URL.createObjectURL(file)); setR(null); setErr(null); setBusy(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch(`${API}/api/vision/inspect-leaf`, { method: 'POST', body: fd });
      const j = await res.json().catch(() => null);
      if (!res.ok || !j || j.status !== 'success') throw new Error(j?.message || `HTTP ${res.status}`);
      setR(j);
    } catch (x) {
      setErr(x instanceof TypeError ? 'Sunucuya ulaşılamadı. Bağlantıyı kontrol edip tekrar deneyin.' : `Görüntü analiz edilemedi: ${x.message}`);
    } finally { setBusy(false); }
  };

  return (
    <section className="lc" aria-labelledby="lc-h">
      <h3 id="lc-h">Marul Yaprağı Hastalık Kontrolü</h3>
      <p className="lc-note">Bir marul yaprağı fotoğrafı yükleyin; model mildiyö, diğer mantar, bakteriyel ve viral belirtileri arar.</p>
      <div className="lc-row">
        <label>Yaprak görüntüsü: <input type="file" accept="image/*" onChange={pick} disabled={busy} /></label>
        {prev && <img className="lc-prev" src={prev} alt="Seçilen yaprak önizlemesi" />}
      </div>
      <div className="lc-out" aria-live="polite">
        {busy && <p>Analiz ediliyor…</p>}
        {err && <p className="lc-err">{err}</p>}
        {r && (
          <>
            <div>
              <span className="lc-diag" style={{ color: r.color }}>{r.diagnosis}</span>
              {r.confidence != null && <> · Güven {pct(r.confidence)}</>}
              {r.confident === false && <span className="lc-unsure">Emin değilim</span>}
            </div>
            {r.top3?.length > 0 && (
              <ul className="lc-top">
                {r.top3.map((t) => (
                  <li key={t.class}>
                    <span>{t.label}</span>
                    <span className="lc-bar" aria-hidden="true"><i style={{ width: `${t.prob * 100}%` }} /></span>
                    <b>{pct(t.prob)}</b>
                  </li>
                ))}
              </ul>
            )}
            <p>{r.recommendation}</p>
            {r.note && <p className="lc-note">{r.note}</p>}
            {r.macro_f1 && <p className="lc-note">Model makro-F1: {r.macro_f1.value.toFixed(2).replace('.', ',')} (%95 GA {r.macro_f1.ci.map((v) => v.toFixed(2).replace('.', ',')).join('–')}, 5 katlı çapraz doğrulama)</p>}
          </>
        )}
      </div>
      <p className="lc-warn">Az sayıda açık lisanslı fotoğrafla (309 özgün görüntü grubu) eğitildi; mantar ve bakteri sınıflarında zayıftır, kesin tanı yerine geçmez.</p>
    </section>
  );
}
