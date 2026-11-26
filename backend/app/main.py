from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

from app.db import init_db, close_db, insert_metrics, get_historical_data, get_profile, update_profile
from app import db
from app.vision import get_verdify_vision_data, diagnose_leaf_image
from app.scada import get_scada_telemetry

app = FastAPI()

@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

connected_clients = set()

@app.post("/api/telemetry")
async def api_telemetry(payload: dict):
    """Köprünün ilettiği sensör ölçümü: veritabanına yazılır ve arayüze canlı yayınlanır."""
    if db.pool is None:  # kaydedilemeyecek mesaja "success" deme; köprü yeniden denesin
        return JSONResponse(status_code=503, content={"detail": "Veritabanı bağlı değil"})

    # Broadcast raw sensor data to UI
    await broadcast_message({"type": "sensor_update", "data": payload})
    
    try:
        await insert_metrics(payload)
    except Exception as e:
        print(f"Database Insert Error: {e}")
        
    return {"status": "success"}

async def broadcast_message(message: dict):
    if not connected_clients:
        return
    
    dead_clients = set()
    msg_str = json.dumps(message)
    for client in connected_clients:
        try:
            await client.send_text(msg_str)
        except Exception:
            dead_clients.add(client)
            
    for client in dead_clients:
        connected_clients.discard(client)

# Risk: Grafana saatlik verisiyle 6 saat sonrası VPD tahmini + eşik kuralı (app/ml/forecast.py)
async def _forecast(end_date=None):
    from app.ml import forecast
    try:
        return {"status": "success", **await asyncio.to_thread(forecast.predict, end_date)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/ml/predict_today")
async def api_ml_predict_today():
    from app import vision
    r = await _forecast()
    if r["status"] == "success":
        leaf = await db.get_latest_leaf()
        r["priority"] = vision.alarm_priority(r["alarm_active"], leaf, datetime.now(timezone.utc))
        r["leaf_moist_prob"] = leaf["moist_prob"]
    return r

@app.get("/api/ml/predict_date")
async def api_ml_predict_date(date: str):
    return await _forecast(date)

@app.get("/api/ml/compare")
def api_ml_compare():
    """eval_models.py'nin yazdığı model karşılaştırması (zaman bazlı değerlendirme); henüz çalıştırılmadıysa data=None."""
    try:
        with open(os.path.join(os.path.dirname(__file__), "ml", "eval_results.json"), encoding="utf-8") as f:
            return {"data": json.load(f)}
    except FileNotFoundError:
        return {"data": None}

@app.on_event("startup")
async def startup_event():
    await init_db()
    asyncio.create_task(_db_retry_loop())

async def _db_retry_loop():
    """Açılışta veritabanına ulaşılamadıysa dakikada bir yeniden dener."""
    while db.pool is None:
        await asyncio.sleep(60)
        try:
            await init_db()
        except Exception as e:
            print(f"db retry: {type(e).__name__}")

_last_hit = time.time()

@app.middleware("http")
async def _touch(request, call_next):
    global _last_hit
    _last_hit = time.time()
    return await call_next(request)

async def _warm_loop():
    """Cache'i (panel TTL 30 sn, arşiv CSV 10 dk) arka planda sıcak tut; kullanıcı isteği soğuk indirmeyi beklemesin."""
    from app import public_data as pdata
    while True:
        if time.time() - _last_hit > 300:  # arayüz kapalıysa Verdify'ı boşuna yorma
            await asyncio.sleep(25)
            continue
        for fn in (pdata.latest_conditions, pdata.weather_latest, pdata.monitoring_charts, pdata.dew_trend, pdata.kpi_24h,
               pdata.equipment_hours, pdata.crop_stress):
            try:
                await asyncio.to_thread(fn)
            except Exception as e:
                print(f"warm {fn.__name__}: {e}")
        await asyncio.sleep(25)

RETRAIN_DAYS = 7  # tahmin modeli bu kadar günden eskiyse kendiliğinden yeniden eğitilir

async def _retrain_loop():
    """VPD tahmin modelini (forecast.py) arka planda, yaşına göre kendi kendine yeniler. Hata olursa eski model kalır."""
    from app.ml import forecast
    await asyncio.sleep(60)  # açılış yükü bitsin
    while True:
        try:
            if time.time() - os.path.getmtime(forecast.PATH) > RETRAIN_DAYS * 86400:
                await asyncio.to_thread(forecast.train)
                forecast._bundle = None  # sonraki tahmin yeni dosyayı yükler
            ev = os.path.join(os.path.dirname(__file__), "ml", "eval_results.json")
            if not os.path.exists(ev) or time.time() - os.path.getmtime(ev) > RETRAIN_DAYS * 86400:
                # ayrı süreç: dakikalarca süren torch eğitimi API'yi kilitlemesin
                await asyncio.to_thread(subprocess.run, [sys.executable, "eval_models.py"], check=True, timeout=3600,
                                        cwd=os.path.join(os.path.dirname(__file__), ".."), capture_output=True)
        except Exception as e:
            print(f"retrain: {e}")
        await asyncio.sleep(3600)

@app.on_event("startup")
async def warm_startup():
    asyncio.create_task(_warm_loop())
    asyncio.create_task(_retrain_loop())

@app.on_event("shutdown")
async def shutdown_event():
    await close_db()

@app.get("/")
def read_root():
    return {"message": "Greenhouse AI API is running."}

@app.get("/api/analytics/historical")
async def api_historical_data(hours: int = 24):
    data = await get_historical_data(hours=max(1, min(hours, 720)))  # en fazla 30 gün
    return {"data": data}

# --- Gerçek veri: Verdify Grafana (verdify-tsdb); erişilemezse yerel TimescaleDB (saatlik arşiv) ---
@app.get("/api/conditions/latest")
async def api_latest_conditions():
    from app.db import get_latest_data
    from app import public_data as pdata
    data = await asyncio.to_thread(pdata.latest_conditions) or await get_latest_data()
    return {"data": data}

@app.get("/api/conditions/date")
async def api_conditions_by_date(date: str):
    from app.db import get_daily_average
    data = await get_daily_average(date)
    return {"data": data}

@app.get("/api/trends/date")
async def api_trends_by_date(date: str):
    from app.db import get_daily_trends
    data = await get_daily_trends(date)
    return {"data": data}

@app.get("/api/weather/latest")
async def api_latest_weather():
    from app.db import get_latest_outdoor_weather
    from app import public_data as pdata
    data = await asyncio.to_thread(pdata.weather_latest) or await get_latest_outdoor_weather()
    return {"data": data}

@app.get("/api/weather/solar-trend")
async def api_solar_trend(range: str = "day"):
    from app import public_data as pdata
    return {"data": await asyncio.to_thread(pdata.solar_trend, range)}

@app.get("/api/weather/dew-trend")
async def api_dew_trend():
    from app import public_data as pdata
    return {"data": await asyncio.to_thread(pdata.dew_trend)}

@app.get("/api/monitoring/charts")
async def api_monitoring_charts(days: int = 7):
    from app import public_data as pdata
    return {"data": await asyncio.to_thread(pdata.monitoring_charts, days)}

@app.get("/api/monitoring/kpi")
async def api_monitoring_kpi():
    from app import public_data as pdata
    return {"data": await asyncio.to_thread(pdata.kpi_24h)}

@app.get("/api/monitoring/equipment")
async def api_monitoring_equipment():
    from app import public_data as pdata
    return {"data": await asyncio.to_thread(pdata.equipment_hours)}

@app.get("/api/crops/stress")
async def api_crop_stress():
    from app import public_data as pdata
    return {"data": await asyncio.to_thread(pdata.crop_stress)}

@app.get("/api/energy/day")
async def api_energy_day(date: str):
    # Enerji verisi (Shelly) Verdify'ın herkese açık kaynaklarında yok; sahte sıfır yerine "veri yok" dön
    return {"data": None}

class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    email: str | None = Field(default=None, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

@app.get("/api/profile")
async def api_get_profile():
    return {"data": await get_profile()}

@app.put("/api/profile")
async def api_put_profile(p: ProfileIn):
    return {"data": await update_profile(p.name.strip(), p.email or None)}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.discard(websocket)

# --- COMPUTER VISION & CROP DIAGNOSTICS ENDPOINTS ---
MAX_UPLOAD = 5_000_000
@app.get("/api/vision/crop-health")
def api_vision_crop_health():  # düz def: bloklayan requests thread havuzunda çalışır, event loop kilitlenmez
    return get_verdify_vision_data()

@app.post("/api/vision/inspect-leaf")
async def api_vision_inspect_leaf(file: UploadFile = File(...)):
    contents = await file.read(MAX_UPLOAD + 1)
    if len(contents) > MAX_UPLOAD:
        return JSONResponse(status_code=413, content={"detail": "Dosya 5 MB'dan büyük"})
    r = await asyncio.to_thread(diagnose_leaf_image, contents)  # model çalışırken event loop kilitlenmesin
    if r.get("source") == "onnx":
        await db.insert_leaf(file.filename, r)  # form: dosya adı, zaman ve model sonucu veritabanında tutulur
    return r

# --- INDUSTRIAL SCADA & EQUIPMENT TELEMETRY ENDPOINT ---
@app.get("/api/monitoring/scada")
def api_monitoring_scada():
    return get_scada_telemetry()
