import { API } from '../../api';
import React, { useEffect, useState } from 'react';
import './ModelComparison.css';

const f = (v) => (v == null ? '–' : v.toFixed(3).replace('.', ','));
const rng = (c) => (c ? `${f(c[0])}–${f(c[1])}` : '');
const NOTE = {
  persistence: 'Son ölçümü olduğu gibi tekrarlar (taban çizgisi)',
  'saatlik klimatoloji': 'Günün saatine göre ortalama (taban çizgisi)',
  GBM: 'Canlı sistemde kullanılan model',
  'CNN-LSTM': 'Derin öğrenme alternatifi',
};

export default function ModelComparison() {
  const [d, setD] = useState(undefined);
  useEffect(() => {
    fetch(`${API}/api/ml/compare`).then((r) => r.json()).then((j) => setD(j.data), () => setD(null));
  }, []);
  if (d === undefined) return null;
  if (!d) return <p className="cmp-note">Model karşılaştırması henüz üretilmedi (docker exec greenhouse_api python eval_models.py).</p>;
  const best = Math.min(...d.rows.map((r) => r.MAE));
  return (
    <section className="cmp" aria-labelledby="cmp-h">
      <h3 id="cmp-h">Model doğruluğu: {d.horizon_h} saat sonrası VPD tahmini</h3>
      <p className="cmp-note">
        {d.from} – {d.to} arası {d.samples} saat, {d.blocks} ardışık test bloğu (eğitim hep testten öncedir). Risk = tahmin &lt; {d.threshold} kPa;
        testte risk oranı %{Math.round(d.risk_rate * 100)}. Köşeli parantez: %95 güven aralığı.
      </p>
      <div className="cmp-scroll">
        <table>
          <thead>
            <tr><th>Model</th><th>MAE (kPa) ↓</th><th>PR-AUC ↑</th><th>Yakalama ↑</th><th>MCC ↑</th></tr>
          </thead>
          <tbody>
            {d.rows.map((r) => (
              <tr key={r.model} className={r.MAE === best ? 'cmp-best' : ''}>
                <th scope="row">{r.model}<span>{NOTE[r.model]}</span></th>
                <td>{f(r.MAE)}<span>{rng(r.ci.MAE)}</span></td>
                <td>{f(r.PRAUC)}<span>{rng(r.ci.PRAUC)}</span></td>
                <td>{f(r.rec)}<span>{rng(r.ci.rec)}</span></td>
                <td>{f(r.MCC)}<span>{rng(r.ci.MCC)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {d.cnn_minus_gbm && (
        <p className="cmp-note">
          CNN-LSTM − GBM farkı (eşli bootstrap, %95): {Object.entries(d.cnn_minus_gbm).map(([k, v]) => (
            `${k === 'PRAUC' ? 'PR-AUC' : k} ${f(v.diff)} [${f(v.ci[0])}; ${f(v.ci[1])}] ${v.ci[0] > 0 || v.ci[1] < 0 ? 'anlamlı' : 'anlamlı değil'}`
          )).join(' · ')}
        </p>
      )}
    </section>
  );
}
