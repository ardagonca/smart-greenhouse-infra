import React, { useEffect, useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import '../pages/Monitoring.css';

// Verdify'ın herkese açık sera kamerası anlık görüntüleri (kaynakta da 30 sn'de bir yenilenir)
const CAMS = [{ id: 'greenhouse_1', label: 'Kamera 1' }, { id: 'greenhouse_2', label: 'Kamera 2' }];
const SRC = (id) => `https://api.verdify.ai/api/v1/public/cameras/${id}/latest.jpg?h=720&_=${Date.now()}`;

function Cam({ id, label, active }) {
  const [src, setSrc] = useState(null);
  const [at, setAt] = useState(null);
  const [err, setErr] = useState(false);
  const reduce = useReducedMotion();

  useEffect(() => {
    if (!active) return; // sekme gizliyken istek yok
    let live = true;
    const load = () => {
      const u = SRC(id);
      const img = new Image(); // önce yükle, sonra değiştir: yenilemede titreme olmaz
      img.onload = () => live && (setSrc(u), setAt(new Date()), setErr(false));
      img.onerror = () => live && setErr(true);
      img.src = u;
    };
    load();
    const t = setInterval(load, 30000);
    return () => { live = false; clearInterval(t); };
  }, [id, active]);

  return (
    <figure className="mn-cam">
      <div className="mn-cam-frame">
        {src && <motion.img src={src} alt={`${label} canlı sera görüntüsü`} initial={{ opacity: reduce ? 1 : 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4 }} />}
        {!src && <div className="mn-cam-empty">{err ? 'Görüntü alınamadı. Bağlantı gelince otomatik denenir.' : 'Yükleniyor…'}</div>}
        {src && <span className={`mn-cam-badge${err ? ' off' : ''}`}>{err ? 'Bağlantı yok' : 'Canlı'}</span>}
      </div>
      <figcaption>
        <strong>{label}</strong>
        <span>{err && src ? 'Bağlantı koptu, son görüntü gösteriliyor. ' : ''}{at ? `Son güncelleme ${at.toLocaleTimeString('tr-TR')}` : 'Henüz görüntü yok'}, 30 sn'de bir yenilenir</span>
        <span role="status" style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>{err ? `${label} bağlantısı koptu` : ''}</span>
      </figcaption>
    </figure>
  );
}

export default function LiveCameras({ active = true }) {
  return (
    <section className="mn-sec" aria-labelledby="mn-cams-h">
      <div className="mn-sec-head">
        <div>
          <h3 id="mn-cams-h">Canlı sera kameraları</h3>
          <p className="mn-sub">Kaynak: Verdify herkese açık kamera görüntüleri.</p>
        </div>
      </div>
      <div className="mn-cams">
        {CAMS.map(c => <Cam key={c.id} {...c} active={active} />)}
      </div>
    </section>
  );
}
