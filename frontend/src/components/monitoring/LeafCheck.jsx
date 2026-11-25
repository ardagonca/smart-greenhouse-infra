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
      <h3 id="lc-h">Yaprak Hastalık Kontrolü</h3>
      <p className="lc-note">Bir yaprak fotoğrafı yükleyin, model olası hastalığı tahmin etsin.</p>
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
            {r.model_accuracy != null && <p className="lc-note">Model test doğruluğu: {pct(r.model_accuracy > 1 ? r.model_accuracy / 100 : r.model_accuracy)}</p>}
          </>
        )}
      </div>
      <p className="lc-warn">PlantVillage laboratuvar fotoğraflarıyla eğitildi; gerçek sera koşullarında doğruluk daha düşük olabilir.</p>
    </section>
  );
}
