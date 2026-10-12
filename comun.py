"""Cosas compartidas por los scripts del publicador.

Solo usa la biblioteca estándar de Python, así el chequeo rápido de GitHub
("¿hay algo para publicar?") corre sin instalar nada.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
COLA = RAIZ / "cola.json"
REGISTRO = RAIZ / "registro.txt"
CANDADO = RAIZ / ".candado"

# Argentina no tiene horario de verano desde 2009: siempre UTC-3.
AR = timezone(timedelta(hours=-3), "ART")

TIPOS = ("carrusel", "imagen", "reel")
ESTADOS = ("borrador", "aprobado", "publicado", "error")
CAMPOS = ("id", "fecha_hora", "tipo", "archivos", "pie", "alt", "estado", "resultado")

# Si una pieza aprobada no salió a su hora (GitHub caído, aprobación tarde),
# se publica igual solo si el atraso es menor que esto y sigue siendo el mismo día.
MAX_ATRASO_MIN = int(os.environ.get("MAX_ATRASO_MIN", "180"))

DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def preparar_consola():
    """Que los acentos no rompan la consola de Windows."""
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ---------------------------------------------------------------- horas

def ahora():
    return datetime.now(AR)


def leer_fecha(texto):
    """'2026-10-14T20:30:00-03:00' (o sin zona: se toma hora de Argentina)."""
    if isinstance(texto, datetime):
        dt = texto
    else:
        dt = datetime.fromisoformat(str(texto).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=AR)
    return dt.astimezone(AR)


def iso(dt):
    return leer_fecha(dt).isoformat(timespec="seconds")


def fmt(dt):
    dt = leer_fecha(dt)
    return f"{DIAS[dt.weekday()]} {dt:%d/%m} {dt:%H:%M}"


def falta(desde, hasta):
    """'en 2 d 6 h', 'en 35 min', 'hace 10 min'."""
    seg = int((hasta - desde).total_seconds())
    pref = "en" if seg >= 0 else "hace"
    seg = abs(seg)
    d, resto = divmod(seg, 86400)
    h, resto = divmod(resto, 3600)
    m = resto // 60
    if d:
        txt = f"{d} d {h} h"
    elif h:
        txt = f"{h} h {m} min"
    else:
        txt = f"{m} min"
    return f"{pref} {txt}"


# ---------------------------------------------------------------- cola

def cargar_cola(ruta=COLA):
    ruta = Path(ruta)
    if not ruta.exists():
        return []
    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)
    if not isinstance(datos, list):
        raise ValueError("cola.json tiene que ser una lista de piezas: [ {...}, {...} ]")
    return datos


def clave_orden(p):
    try:
        return (leer_fecha(p.get("fecha_hora")), str(p.get("id")))
    except Exception:
        return (datetime.max.replace(tzinfo=AR), str(p.get("id")))


def ordenar(piezas):
    piezas.sort(key=clave_orden)
    return piezas


def guardar_cola(piezas, ruta=COLA):
    """Escritura segura: primero a un temporal y después se reemplaza."""
    ruta = Path(ruta)
    tmp = ruta.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(piezas, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, ruta)


def buscar(piezas, id_):
    for p in piezas:
        if str(p.get("id")) == str(id_):
            return p
    return None


def pendientes_que_tocan(piezas, momento):
    """Aprobadas cuya hora ya pasó (lo único que se publica)."""
    salida = []
    for p in piezas:
        if p.get("estado") != "aprobado":
            continue
        try:
            if leer_fecha(p["fecha_hora"]) <= momento:
                salida.append(p)
        except Exception:
            salida.append(p)  # la validación la va a marcar como error
    return sorted(salida, key=clave_orden)


def vencida(p, momento):
    """None si todavía se puede publicar; si no, el motivo."""
    fh = leer_fecha(p["fecha_hora"])
    atraso = (momento - fh).total_seconds() / 60
    if fh.date() != momento.date():
        return (f"no salió el {fh:%d/%m} y hoy ya es {momento:%d/%m}. "
                "No se publica en otro día (las fechas impresas tienen que coincidir).")
    if atraso > MAX_ATRASO_MIN:
        return f"pasaron {int(atraso)} min de la hora prevista (el máximo es {MAX_ATRASO_MIN})."
    return None


# ---------------------------------------------------------------- textos

RE_HASHTAG = re.compile(r"(?<![\w&])#\w+", re.UNICODE)
RE_MENCION = re.compile(r"(?<![\w@])@[\w.]+", re.UNICODE)


def hashtags(texto):
    return RE_HASHTAG.findall(texto or "")


def menciones(texto):
    return RE_MENCION.findall(texto or "")


def normalizar(texto):
    return re.sub(r"\s+", " ", (texto or "")).strip()


def limpiar(texto):
    """Saca cualquier token de un mensaje antes de mostrarlo o guardarlo."""
    texto = str(texto)
    for nombre in ("IG_TOKEN", "GH_PAT"):
        valor = os.environ.get(nombre, "").strip()
        if len(valor) > 8:
            texto = texto.replace(valor, "***")
    texto = re.sub(r"(access_token=)[^&\s\"']+", r"\1***", texto)
    texto = re.sub(r"\bIG[A-Za-z0-9_-]{40,}", "***", texto)
    texto = re.sub(r"\bEA[A-Za-z0-9]{40,}", "***", texto)
    return texto


# ---------------------------------------------------------------- registro

def log(msg):
    print(f"[{ahora():%d/%m %H:%M:%S}] {limpiar(msg)}", flush=True)


def registrar(linea):
    """Una línea por evento en registro.txt (queda en GitHub junto con cola.json)."""
    with open(REGISTRO, "a", encoding="utf-8", newline="\n") as f:
        f.write(f"{ahora():%Y-%m-%d %H:%M} · {limpiar(linea)}\n")


# ---------------------------------------------------------------- candado

class Candado:
    """Evita dos corridas a la vez sobre la misma cola (en GitHub, además,
    el workflow usa 'concurrency'). Si quedó un candado viejo (> 30 min), se pisa."""

    def __init__(self, ruta=CANDADO, vencimiento_seg=1800):
        self.ruta = Path(ruta)
        self.vencimiento = vencimiento_seg
        self.tomado = False

    def __enter__(self):
        for _ in range(2):
            try:
                fd = os.open(self.ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as f:
                    f.write(f"{os.getpid()} {time.time()}\n")
                self.tomado = True
                return self
            except FileExistsError:
                edad = time.time() - self.ruta.stat().st_mtime
                if edad > self.vencimiento:
                    log("Había un candado viejo de otra corrida; lo saco.")
                    self.ruta.unlink(missing_ok=True)
                    continue
                raise SystemExit("Otra corrida está usando la cola ahora mismo. Salgo sin hacer nada.")
        raise SystemExit("No pude tomar el candado de la cola.")

    def __exit__(self, *exc):
        if self.tomado:
            self.ruta.unlink(missing_ok=True)
        return False
