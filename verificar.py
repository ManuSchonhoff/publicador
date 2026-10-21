"""Prueba en seco, sin internet: revisa cola.json y muestra qué se publicaría y cuándo.

Uso:
  python verificar.py                          revisa todo y muestra el calendario
  python verificar.py --ahora 2026-10-14T20:40 simula qué publicaría una corrida a esa hora
  python verificar.py --ordenar                ordena cola.json por hora y la guarda
  python verificar.py --resumen                solo el calendario corto (lo usa GitHub)

Sale con código 1 si encuentra algún error.
"""

import argparse
import re
import struct
import sys
from pathlib import Path

from comun import (AR, ESTADOS, RAIZ, TIPOS, CAMPOS, LIMITE_24H, MAX_ATRASO_MIN, ahora, buscar,
                   cargar_cola, clave_orden, falta, fmt, guardar_cola, hashtags, leer_fecha, menciones,
                   ordenar, pendientes_que_tocan, preparar_consola, vencida)

MAX_PIE = 2200
MAX_HASHTAGS = 30
MAX_MENCIONES = 20
MAX_ALT = 1000
MAX_JPG_MB = 8
MAX_REEL_MB_IG = 300
MAX_ARCHIVO_MB_GITHUB = 95       # GitHub rechaza archivos de 100 MB o más
MAX_ARCHIVO_MB_WEB = 25          # la subida por la web de GitHub no acepta más
MAX_HISTORIA_MB = 100            # video de historia: hasta 100 MB y de 3 a 60 s (referencia de IG User Media)
MAX_HISTORIA_SEG = 60
IMAGENES_HISTORIA = (".jpg", ".jpeg")
VIDEOS_HISTORIA = (".mp4", ".mov")
RATIOS = {"4:5": 4 / 5, "1:1": 1.0, "9:16": 9 / 16}
DIAS_CORTOS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")

# Nombres que nunca van en lo publicable (la casa y el equipo). El repo es público: no se escriben acá,
# se comparan por su huella (sha256 de la palabra o del par de palabras, en minúsculas y sin tildes).
NOMBRES_PRIVADOS = {
    "26409c76a229a54a0ae9", "16814e8cd706b29de1ba", "cca457407f24b80c72d8",
    "dbde6e431edd7f4672f0", "d2caa82cdb5a0a33f42b", "8ec98ed17b2fba4b6065",
    "04017fc8b5ab929063f7", "40e33c9cd651d7ed6a9a",
}


def nombre_privado(texto):
    """Devuelve la palabra (o el par de palabras) de la lista privada que aparece en el texto, o None."""
    import hashlib
    import unicodedata
    plano = unicodedata.normalize("NFKD", texto.lower())
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    palabras = re.findall(r"[a-zñ]+", plano)
    for c in palabras + [f"{x} {y}" for x, y in zip(palabras, palabras[1:])]:
        if hashlib.sha256(c.encode()).hexdigest()[:20] in NOMBRES_PRIVADOS:
            return c
    return None


# Lo prohibido en lo publicable (error) y lo dudoso (aviso). Se busca en el pie, en el alt
# y en el texto de la imagen de las historias (campo "texto").
PROHIBIDO = [
    (r"whats\s*app|wa\.me", "WhatsApp todavía no es un canal activo"),
    (r"cada\s+(4|cuatro)\s+horas", "dice 'cada 4 horas' (son tres copias por día)"),
    (r"@\s*trackear\.pro\b", "la cuenta es @trackearpro, sin punto"),
    (r"\b(cepo|arca|uif|cuevas?)\b", "no se habla de cepo, ARCA, UIF ni cuevas"),
    (r"cambio\s+norte", "'Cambio Norte' es el nombre de la grabación: va tapado"),
    (r"(?<!no )(?<!ni )\b(compramos|vendemos)\b(?:\s+\S+){0,3}?\s+(divisas|d[oó]lares|monedas?|euros|reales)\b",
     "dice que compramos o vendemos divisas (somos un sistema de gestión)"),
]
DUDOSO = [
    (r"\bseptiembre\b", "¿fecha de la grabación? (septiembre iba tapado)"),
    (r"(?<!no )(?<!ni )\b(compramos|vendemos)\b", "¿dice que compramos o vendemos? (no compramos ni vendemos divisas)"),
    (r"\ben\s+vivo\b|\bvivos?\b|\blive\b", "¿habla de vivos? (no hay vivos)"),
    (r"export\w*.{0,60}(sin\s+pag|no\s+pag|deja\w*\s+de\s+pag)|(sin\s+pag|no\s+pag).{0,60}export",
     "¿menciona exportar sin pagar? (no se dice)"),
    (r"por\s+operaci[oó]n", "¿ganancia por operación? (la ganancia sale del patrimonio)"),
    (r"usuario\w*\s+de\s+prueba|demo@|test@", "¿usuario de prueba?"),
]


# ---------------------------------------------------------------- MP4 sin ffprobe

def _cajas(datos, ini, fin):
    i = ini
    while i + 8 <= fin:
        tam, tipo = struct.unpack(">I4s", datos[i:i + 8])
        cab = 8
        if tam == 1:
            tam = struct.unpack(">Q", datos[i + 8:i + 16])[0]
            cab = 16
        elif tam == 0:
            tam = fin - i
        if tam < cab:
            break
        yield tipo.decode("latin-1"), i + cab, i + tam
        i += tam


def info_mp4(ruta):
    """Ancho, alto, duración y códec del video leyendo las cajas del MP4/MOV."""
    ruta = Path(ruta)
    moov = None
    mdat_antes = False
    with open(ruta, "rb") as f:
        f.seek(0, 2)
        total = f.tell()
        pos = 0
        while pos + 8 <= total:
            f.seek(pos)
            cab = f.read(16)
            tam, tipo = struct.unpack(">I4s", cab[:8])
            largo_cab = 8
            if tam == 1:
                tam = struct.unpack(">Q", cab[8:16])[0]
                largo_cab = 16
            elif tam == 0:
                tam = total - pos
            if tam < 8:
                break
            if tipo == b"moov":
                f.seek(pos + largo_cab)
                moov = f.read(tam - largo_cab)
                break
            if tipo == b"mdat":
                mdat_antes = True
            pos += tam
    if moov is None:
        raise ValueError("no encuentro la caja 'moov' (¿el archivo está completo?)")

    info = {"ancho": None, "alto": None, "duracion": None, "codec": None, "moov_primero": not mdat_antes}
    for tipo, a, b in _cajas(moov, 0, len(moov)):
        if tipo == "mvhd":
            ver = moov[a]
            if ver == 1:
                escala, dur = struct.unpack(">IQ", moov[a + 20:a + 32])
            else:
                escala, dur = struct.unpack(">II", moov[a + 12:a + 20])
            if escala:
                info["duracion"] = dur / escala
        elif tipo == "trak":
            tk = {}
            for t2, a2, b2 in _cajas(moov, a, b):
                if t2 == "tkhd":
                    ancho, alto = struct.unpack(">II", moov[b2 - 8:b2])
                    mat = struct.unpack(">9i", moov[b2 - 44:b2 - 8])
                    ancho, alto = ancho / 65536, alto / 65536
                    if mat[0] == 0 and mat[1] != 0:  # rotado 90°
                        ancho, alto = alto, ancho
                    tk["ancho"], tk["alto"] = round(ancho), round(alto)
                elif t2 == "mdia":
                    for t3, a3, b3 in _cajas(moov, a2, b2):
                        if t3 == "hdlr":
                            tk["handler"] = moov[a3 + 8:a3 + 12].decode("latin-1")
                        elif t3 == "minf":
                            for t4, a4, b4 in _cajas(moov, a3, b3):
                                if t4 == "stbl":
                                    for t5, a5, b5 in _cajas(moov, a4, b4):
                                        if t5 == "stsd" and b5 - a5 >= 16:
                                            tk["codec"] = moov[a5 + 12:a5 + 16].decode("latin-1")
            if tk.get("handler") == "vide" and tk.get("ancho"):
                info["ancho"], info["alto"] = tk["ancho"], tk["alto"]
                info["codec"] = tk.get("codec")
    return info


# ---------------------------------------------------------------- validación

def _ratio_nombre(ancho, alto, tolerancia=0.012):
    r = ancho / alto
    for nombre, valor in RATIOS.items():
        if abs(r - valor) / valor <= tolerancia:
            return nombre
    return None


def _ruta_repo(rel):
    """Ruta dentro del repo, o None si apunta afuera."""
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        return None
    return RAIZ / rel


def validar_imagen(rel, tipo, errores, avisos):
    from PIL import Image  # solo acá: el resto no necesita Pillow

    ruta = _ruta_repo(rel)
    if ruta is None:
        errores.append(f"{rel}: la ruta tiene que ser relativa y dentro del repo (por ejemplo media/2026-10-14/p01.jpg)")
        return None
    if not ruta.exists():
        errores.append(f"{rel}: no existe")
        return None
    mb = ruta.stat().st_size / 1e6
    if mb > MAX_JPG_MB:
        errores.append(f"{rel}: pesa {mb:.1f} MB (Instagram acepta hasta {MAX_JPG_MB} MB)")
    try:
        with Image.open(ruta) as im:
            formato, (ancho, alto), modo = im.format, im.size, im.mode
    except Exception as e:
        errores.append(f"{rel}: no se puede abrir como imagen ({e})")
        return None
    if formato != "JPEG":
        errores.append(f"{rel}: es {formato}; la API solo acepta JPEG (corré preparar.py, que la convierte)")
    if modo not in ("RGB", "L"):
        avisos.append(f"{rel}: modo de color {modo}; conviene RGB")
    if not 320 <= ancho <= 1440:
        errores.append(f"{rel}: mide {ancho} px de ancho (Instagram acepta de 320 a 1440)")
    nombre = _ratio_nombre(ancho, alto)
    permitidos = ("9:16",) if tipo in ("portada", "historia") else ("4:5", "1:1")
    if nombre not in permitidos:
        errores.append(f"{rel}: {ancho}×{alto} no es {' ni '.join(permitidos)}")
    elif tipo == "historia" and (ancho, alto) != (1080, 1920):
        avisos.append(f"{rel}: mide {ancho}×{alto}; las historias se diseñan en 1080×1920")
    return nombre


def validar_video(rel, errores, avisos, tipo="reel"):
    historia = tipo == "historia"
    ruta = _ruta_repo(rel)
    if ruta is None:
        errores.append(f"{rel}: la ruta tiene que ser relativa y dentro del repo")
        return
    if not ruta.exists():
        errores.append(f"{rel}: no existe")
        return
    if ruta.suffix.lower() not in (".mp4", ".mov"):
        errores.append(f"{rel}: el {'video de la historia' if historia else 'reel'} tiene que ser .mp4 o .mov")
        return
    mb = ruta.stat().st_size / 1e6
    if mb >= MAX_ARCHIVO_MB_GITHUB:
        errores.append(f"{rel}: pesa {mb:.0f} MB y GitHub no acepta archivos de 100 MB o más; exportalo más liviano")
    elif mb > MAX_ARCHIVO_MB_WEB:
        avisos.append(f"{rel}: pesa {mb:.0f} MB; subilo con GitHub Desktop (la web de GitHub corta en 25 MB)")
    if historia and mb > MAX_HISTORIA_MB:
        errores.append(f"{rel}: pesa {mb:.0f} MB (en historias Instagram acepta hasta {MAX_HISTORIA_MB} MB)")
    elif mb > MAX_REEL_MB_IG:
        errores.append(f"{rel}: pesa {mb:.0f} MB (Instagram acepta hasta 300 MB)")
    try:
        info = info_mp4(ruta)
    except Exception as e:
        errores.append(f"{rel}: no pude leer el video ({e})")
        return
    if info["ancho"] and info["alto"]:
        if _ratio_nombre(info["ancho"], info["alto"]) != "9:16":
            errores.append(f"{rel}: {info['ancho']}×{info['alto']} no es 9:16")
        if info["ancho"] > 1920 or info["alto"] > 3840:
            avisos.append(f"{rel}: {info['ancho']}×{info['alto']} es más grande de lo que Instagram usa (1080×1920)")
    else:
        errores.append(f"{rel}: no encontré la pista de video")
    dur = info["duracion"]
    if dur is not None and historia:
        if dur < 3:
            errores.append(f"{rel}: dura {dur:.1f} s (el mínimo es 3 s)")
        elif dur > MAX_HISTORIA_SEG:
            errores.append(f"{rel}: dura {dur:.0f} s (una historia por API dura hasta {MAX_HISTORIA_SEG} s)")
        if not info.get("moov_primero", True):
            avisos.append(f"{rel}: el índice del video (moov) está al final; Instagram lo pide al principio. "
                          "Si falla, re-exportalo con 'inicio rápido' (ffmpeg: -movflags +faststart)")
    elif dur is not None:
        if dur < 3:
            errores.append(f"{rel}: dura {dur:.1f} s (el mínimo es 3 s)")
        elif dur > 900:
            errores.append(f"{rel}: dura {dur:.0f} s (el máximo por API es 15 min)")
        elif dur > 90:
            avisos.append(f"{rel}: dura {dur:.0f} s; los reels de más de 90 s llegan a menos gente")
    if info["codec"] and info["codec"] not in ("avc1", "avc3", "hvc1", "hev1"):
        errores.append(f"{rel}: el códec es '{info['codec']}'; Instagram pide H.264 o HEVC")
    return info


def _fecha_impresa(pie, fh, errores, avisos):
    """Toda fecha escrita tiene que ser la del día en que sale."""
    dia = fh.date()
    for d, m, a in re.findall(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", pie):
        if (int(d), int(m), int(a)) != (dia.day, dia.month, dia.year):
            errores.append(f"el pie dice {d}/{m}/{a} pero sale el {dia:%d/%m/%Y} (la fecha impresa tiene que ser la del día)")
    for d, m in re.findall(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])", pie):
        if (int(d), int(m)) != (dia.day, dia.month) and 1 <= int(m) <= 12:
            avisos.append(f"menciona {d}/{m} y sale el {dia:%d/%m}: ¿está bien?")


def _validar_historia(p, archivos, errores, avisos):
    """Una historia: 1 imagen JPEG 9:16 o 1 video vertical de 3 a 60 s. Sin pie, sin alt, sin stickers."""
    if len(archivos) != 1:
        errores.append(f"una historia lleva 1 archivo (imagen o video) y tiene {len(archivos)}")
    for a in archivos[:1]:
        ext = Path(str(a)).suffix.lower()
        if ext in IMAGENES_HISTORIA:
            validar_imagen(a, "historia", errores, avisos)
        elif ext in VIDEOS_HISTORIA:
            validar_video(a, errores, avisos, tipo="historia")
        else:
            errores.append(f"{a}: una historia es una imagen JPEG o un video .mp4/.mov "
                           "(corré preparar.py, que pasa el PNG a JPEG)")
    if p.get("portada"):
        avisos.append("las historias no llevan portada: se ignora")
    alt = p.get("alt")
    if (isinstance(alt, list) and any(alt)) or (isinstance(alt, str) and alt.strip()):
        avisos.append("Instagram no tiene texto alternativo en historias: el alt no se manda")
    if p.get("sticker"):
        errores.append(f"lleva sticker ({p['sticker']}) y la API no publica stickers: "
                       "va a mano, o usá una variante __auto sin sticker")
    if not (p.get("texto") or "").strip():
        avisos.append("no tengo el texto de la imagen (campo 'texto'): miralo a ojo antes de aprobar "
                      "(nombres reales, WhatsApp, fechas de grabación)")
    try:
        if int(p.get("orden") or 0) < 1:
            avisos.append("la historia no tiene 'orden' (1, 2, 3…): si hay varias a la misma hora, salen por id")
    except (TypeError, ValueError):
        errores.append(f"'orden' tiene que ser un número y es '{p.get('orden')}'")


def validar_pieza(p, momento=None, chequear_hora=True):
    """Devuelve (errores, avisos) de una pieza. No usa internet."""
    errores, avisos = [], []
    momento = momento or ahora()

    for campo in CAMPOS:
        if campo not in p:
            errores.append(f"falta el campo '{campo}'")
    tipo = p.get("tipo")
    if tipo not in TIPOS:
        errores.append(f"tipo '{tipo}' no vale (carrusel, imagen, reel o historia)")
    if p.get("estado") not in ESTADOS:
        errores.append(f"estado '{p.get('estado')}' no vale ({', '.join(ESTADOS)})")

    fh = None
    try:
        fh = leer_fecha(p.get("fecha_hora"))
        if p.get("fecha_hora") and "T" in str(p["fecha_hora"]) and not re.search(r"[+-]\d\d:\d\d$|Z$", str(p["fecha_hora"])):
            avisos.append("fecha_hora sin zona horaria: se toma como hora de Argentina")
    except Exception:
        errores.append(f"fecha_hora '{p.get('fecha_hora')}' no se entiende (formato: 2026-10-14T20:30:00-03:00)")

    if chequear_hora and fh and p.get("estado") in ("borrador", "aprobado"):
        if fh <= momento:
            if p["estado"] == "aprobado":
                motivo = vencida(p, momento)
                if motivo:
                    errores.append(f"ya no se puede publicar: {motivo} Cambiale la hora y aprobala de nuevo.")
                else:
                    avisos.append(f"la hora ya pasó ({falta(momento, fh)}): sale en la próxima corrida")
            else:
                avisos.append(f"la hora ya pasó ({fmt(fh)}) y sigue en borrador: no va a salir")

    # archivos
    archivos = p.get("archivos") or []
    if not isinstance(archivos, list) or not archivos:
        errores.append("no tiene archivos")
        archivos = []
    if tipo == "carrusel":
        if not 2 <= len(archivos) <= 10:
            errores.append(f"un carrusel lleva de 2 a 10 placas y tiene {len(archivos)}")
        ratios = {validar_imagen(a, tipo, errores, avisos) for a in archivos}
        ratios.discard(None)
        if len(ratios) > 1:
            errores.append(f"las placas tienen formatos distintos ({', '.join(sorted(ratios))}); Instagram recorta todo al de la primera")
    elif tipo == "imagen":
        if len(archivos) != 1:
            errores.append(f"una imagen lleva 1 archivo y tiene {len(archivos)}")
        for a in archivos[:1]:
            validar_imagen(a, tipo, errores, avisos)
    elif tipo == "reel":
        if len(archivos) != 1:
            errores.append(f"un reel lleva 1 video en 'archivos' (la portada va en 'portada') y tiene {len(archivos)}")
        for a in archivos[:1]:
            validar_video(a, errores, avisos)
        if p.get("portada"):
            validar_imagen(p["portada"], "portada", errores, avisos)
        else:
            avisos.append("el reel no tiene portada: Instagram usa el primer cuadro")
    elif tipo == "historia":
        _validar_historia(p, archivos, errores, avisos)

    # pie
    pie = p.get("pie") or ""
    if tipo == "historia":
        if pie.strip():
            errores.append('una historia no lleva pie (la API no lo publica): dejá "pie": ""')
    elif not pie.strip():
        errores.append("el pie está vacío")
    if len(pie) > MAX_PIE:
        errores.append(f"el pie tiene {len(pie)} caracteres (máximo {MAX_PIE})")
    n_tags = len(hashtags(pie))
    if n_tags > MAX_HASHTAGS:
        errores.append(f"el pie tiene {n_tags} hashtags (máximo {MAX_HASHTAGS})")
    if len(menciones(pie)) > MAX_MENCIONES:
        errores.append(f"el pie tiene más de {MAX_MENCIONES} menciones")
    texto_img = (p.get("texto") or "") if tipo == "historia" else ""
    if fh:
        _fecha_impresa(pie, fh, errores, avisos)
        if texto_img:
            err_txt = []
            _fecha_impresa(texto_img, fh, err_txt, avisos)
            errores.extend(e.replace("el pie dice", "la imagen dice") for e in err_txt)
        alt_lista = p.get("alt") if isinstance(p.get("alt"), list) else [p.get("alt") or ""]
        alt_txt = " | ".join(a or "" for a in alt_lista)
        err_alt = []
        _fecha_impresa(alt_txt, fh, err_alt, avisos)
        avisos.extend(e.replace("el pie dice", "el texto alternativo dice") + " (si es a propósito, está bien)" for e in err_alt)
    for url in re.findall(r"https?://\S*trackearpro\.com\S*", pie, re.I):
        if "utm_source" not in url:
            avisos.append(f"el link {url} no lleva UTM")

    # alt
    alt = p.get("alt")
    alts = alt if isinstance(alt, list) else ([alt] if alt else [])
    if tipo in ("carrusel", "imagen"):
        if not alts or not any((a or "").strip() for a in alts):
            avisos.append("no tiene texto alternativo")
        if isinstance(alt, list) and len(alt) not in (1, len(archivos)):
            errores.append(f"hay {len(alt)} textos alternativos para {len(archivos)} placas (uno por placa, o uno solo para todas)")
    for i, a in enumerate(alts if tipo != "reel" else [], 1):  # en reels el alt no se manda
        if a and len(a) > MAX_ALT:
            errores.append(f"el texto alternativo {i} tiene {len(a)} caracteres (máximo {MAX_ALT})")

    # reglas de la marca
    texto = pie + "\n" + "\n".join(a or "" for a in alts) + "\n" + texto_img
    if nombre_privado(texto):
        errores.append("prohibido: nombra a la casa o a alguien del equipo (lista privada)")
    for patron, motivo in PROHIBIDO:
        m = re.search(patron, texto, re.I)
        if m:
            errores.append(f"prohibido: {motivo} ('{m.group(0)}')")
    for patron, motivo in DUDOSO:
        m = re.search(patron, texto, re.I | re.S)
        if m:
            avisos.append(f"{motivo}: '{m.group(0)[:60]}'")

    return errores, avisos


def validar_cola(piezas, momento):
    """Errores generales de la lista (ids repetidos, orden, horas pegadas)."""
    errores, avisos = [], []
    vistos = set()
    for p in piezas:
        i = str(p.get("id"))
        if i in vistos:
            errores.append(f"el id '{i}' está repetido")
        vistos.add(i)
    if [str(p.get("id")) for p in piezas] != [str(p.get("id")) for p in sorted(piezas, key=clave_orden)]:
        errores.append("cola.json no está ordenada por hora (corré: python verificar.py --ordenar)")
    activas = sorted([p for p in piezas if p.get("estado") in ("borrador", "aprobado")], key=clave_orden)
    feed = [p for p in activas if p.get("tipo") != "historia"]
    for a, b in zip(feed, feed[1:]):
        try:
            gap = (leer_fecha(b["fecha_hora"]) - leer_fecha(a["fecha_hora"])).total_seconds() / 60
            if gap < 120:
                avisos.append(f"'{a['id']}' y '{b['id']}' salen con {int(gap)} min de diferencia")
        except Exception:
            pass

    # historias que anuncian un posteo ("Nuevo en el perfil"): salen solo si salió el posteo
    for p in activas:
        dep = p.get("depende_de")
        if not dep:
            continue
        d = buscar(piezas, dep)
        if d is None:
            errores.append(f"'{p['id']}' depende de '{dep}', que no está en la cola")
            continue
        try:
            if leer_fecha(d["fecha_hora"]) > leer_fecha(p["fecha_hora"]):
                errores.append(f"'{p['id']}' sale antes que '{dep}', el posteo que anuncia")
        except Exception:
            pass
        if p.get("estado") == "aprobado" and d.get("estado") not in ("aprobado", "publicado"):
            avisos.append(f"'{p['id']}' está aprobada pero '{dep}' está en {d.get('estado')}: "
                          "la historia no sale hasta que salga el posteo")

    # tope de publicaciones por API en 24 h corridas (feed + historias)
    avisos.extend(pasadas_de_tope(piezas))
    return errores, avisos


def pasadas_de_tope(piezas, limite=None):
    """Días en que la cola (aprobadas, borradores y publicadas) pasa el tope de 24 h corridas."""
    limite = limite or LIMITE_24H
    horas = []
    for p in piezas:
        if p.get("estado") not in ("borrador", "aprobado", "publicado"):
            continue
        try:
            r = p.get("resultado") or {}
            cuando = r.get("publicado_en") if p.get("estado") == "publicado" and r.get("publicado_en") else p["fecha_hora"]
            horas.append(leer_fecha(cuando))
        except Exception:
            continue
    horas.sort()
    peor_por_dia = {}
    j = 0
    for i, h in enumerate(horas):
        while (h - horas[j]).total_seconds() >= 86400:
            j += 1
        n = i - j + 1
        if n > peor_por_dia.get(h.date(), (0, None))[0]:
            peor_por_dia[h.date()] = (n, h)
    salida = []
    for dia, (n, h) in sorted(peor_por_dia.items()):
        if n > limite:
            salida.append(f"el {DIAS_CORTOS[dia.weekday()]} {dia:%d/%m} se juntan {n} publicaciones en 24 h "
                          f"(feed + historias) y el tope es {limite}: las que pasen el tope esperan y, si se "
                          f"atrasan más de {MAX_ATRASO_MIN} min, no salen. Sacá o mové historias de ese día")
    return salida


def por_dia(piezas):
    """{fecha: (feed, historias)} de las piezas activas o publicadas."""
    cuenta = {}
    for p in piezas:
        if p.get("estado") not in ("borrador", "aprobado", "publicado"):
            continue
        try:
            dia = leer_fecha(p["fecha_hora"]).date()
        except Exception:
            continue
        f, h = cuenta.get(dia, (0, 0))
        cuenta[dia] = (f, h + 1) if p.get("tipo") == "historia" else (f + 1, h)
    return cuenta


# ---------------------------------------------------------------- salida

def _vencida_segura(p, momento):
    try:
        return bool(vencida(p, momento))
    except Exception:
        return False


def main():
    preparar_consola()
    ap = argparse.ArgumentParser(description="Revisa cola.json sin internet.")
    ap.add_argument("--ahora", help="simular otra hora, ej. 2026-10-14T20:40")
    ap.add_argument("--ordenar", action="store_true", help="ordenar cola.json por hora y guardarla")
    ap.add_argument("--resumen", action="store_true", help="solo el calendario")
    ap.add_argument("--cola", default=None, help="otra cola.json (para pruebas)")
    args = ap.parse_args()

    from comun import COLA
    ruta_cola = Path(args.cola) if args.cola else COLA
    momento = leer_fecha(args.ahora) if args.ahora else ahora()

    try:
        piezas = cargar_cola(ruta_cola)
    except Exception as e:
        print(f"ERROR: cola.json no se puede leer: {e}")
        return 1

    if args.ordenar:
        ordenar(piezas)
        guardar_cola(piezas, ruta_cola)
        print("Listo: cola.json quedó ordenada por hora.")

    simulado = " (simulado)" if args.ahora else ""
    print(f"Ahora{simulado}: {fmt(momento)} (hora Argentina) · {len(piezas)} piezas en cola.json\n")
    if not piezas:
        print("La cola está vacía. Para sumar una pieza: python preparar.py 2026-10-14")
        return 0

    print(f"{'CUÁNDO':<16} {'ID':<22} {'TIPO':<9} {'ARCH':>4}  {'ESTADO':<10} QUÉ PASA")
    for p in sorted(piezas, key=clave_orden):
        try:
            fh = leer_fecha(p.get("fecha_hora"))
            cuando = fmt(fh)
        except Exception:
            fh, cuando = None, "¿?"
        est = p.get("estado", "¿?")
        if est == "publicado":
            r = p.get("resultado") or {}
            que = f"ya salió · {r.get('permalink') or r.get('ig_id') or ''}"
        elif est == "error":
            r = p.get("resultado") or {}
            que = f"falló: {str(r.get('error', ''))[:70]}"
        elif est == "borrador":
            que = "no sale hasta que la apruebes"
        elif fh and fh <= momento:
            motivo = vencida(p, momento)
            que = f"NO sale: {motivo[:70]}" if motivo else "sale en la próxima corrida"
        elif fh:
            que = f"sale {fmt(fh)} ({falta(momento, fh)})"
        else:
            que = "hora inválida"
        n = len(p.get("archivos") or [])
        print(f"{cuando:<16} {str(p.get('id'))[:22]:<22} {str(p.get('tipo')):<9} {n:>4}  {est:<10} {que}")

    toca = pendientes_que_tocan(piezas, momento)
    vencidas = [p for p in toca if _vencida_segura(p, momento)]
    toca = [p for p in toca if p not in vencidas]
    print()
    if vencidas:
        print(f"Si GitHub corriera ahora{simulado}, NO publicaría (pasó su hora) y las marcaría 'error': "
              + ", ".join(str(p["id"]) for p in vencidas))
    if toca:
        print(f"Si GitHub corriera ahora{simulado}, publicaría: " + ", ".join(str(p["id"]) for p in toca))
    else:
        prox = [p for p in sorted(piezas, key=clave_orden) if p.get("estado") == "aprobado"]
        if prox:
            print(f"Si GitHub corriera ahora{simulado}, no publicaría nada. La próxima aprobada: {prox[0]['id']} ({fmt(prox[0]['fecha_hora'])}).")
        else:
            print("No hay nada aprobado: no se va a publicar nada.")

    dias = {d: v for d, v in por_dia(piezas).items() if d >= momento.date()}
    if dias:
        print(f"\nPor día, feed + historias (tope de la API: {LIMITE_24H} en 24 h): " + " · ".join(
            f"{DIAS_CORTOS[d.weekday()]} {d:%d/%m} {f}+{h}" for d, (f, h) in sorted(dias.items())))

    if args.resumen:
        return 0

    total_err = 0
    err_g, av_g = validar_cola(piezas, momento)
    if err_g or av_g:
        print("\nCola:")
        for e in err_g:
            print(f"  ERROR  {e}")
        for a in av_g:
            print(f"  aviso  {a}")
    total_err += len(err_g)

    for p in sorted(piezas, key=clave_orden):
        if p.get("estado") == "publicado":
            continue
        err, av = validar_pieza(p, momento)
        total_err += len(err)
        estado = "OK" if not err else f"{len(err)} error(es)"
        print(f"\n{p.get('id')} · {p.get('tipo')} · {fmt(p['fecha_hora']) if 'fecha_hora' in p else '¿?'} · {estado}")
        for e in err:
            print(f"  ERROR  {e}")
        for a in av:
            print(f"  aviso  {a}")

    print()
    if total_err:
        print(f"Hay {total_err} error(es). Lo que tenga errores no se aprueba ni se publica.")
        return 1
    print("Todo en orden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
