"""Suma a cola.json, como "borrador", la pieza del feed y las historias de un paquete de carga.

Uso:
  python preparar.py 2026-10-14            usa ../2026-10-07/carga/2026-10-14/ (feed + historias)
  python preparar.py "C:/ruta/al/paquete"  cualquier carpeta con el mismo formato
  python preparar.py todo                  todos los paquetes de carga/ (salta los que esperan video,
                                           lo ya aprobado y las historias cuya hora ya pasó)
  python preparar.py historia ARCHIVO --fecha 2026-10-21 --hora 08:30 [--orden 2] [--id ID]
                                           una historia suelta (imagen 1080×1920 PNG/JPG o video vertical)
  Opciones: --hora 20:30 (la del feed)  --tipo carrusel|imagen|reel  --carga RUTA  --cola RUTA
            --sin-historias  --solo-historias  --media RUTA (otra carpeta de media dentro del repo, para pruebas)

El paquete es la carpeta del día (ej. carga/2026-10-14/), tal como la arma el equipo:
  - Placas del feed: 01.png, 02.png... en ese orden (carrusel; una sola = imagen).
  - Reel: video.mp4 (o cualquier .mp4/.mov que no empiece con "plan-b") y portada.png.
  - pie.txt: el pie tal cual.
  - hora.txt: la primera hora que aparezca (ej. "Miércoles 14/10/2026 · 20:30", "08:30").
    Si no hay, se usa pieza.txt ("hora: 20:30") o la tabla de carga/plan.md.
  - alt.txt: "01.png: texto" (o "01.png" y el texto abajo), uno por placa.
    Si no tiene nombres de placa, todo el texto vale para la pieza.
  - Para el feed se ignoran: historias/, historia-*.png, plan-b_*, *.md, FIJAR.txt y demás notas.
  - ESPERA-VIDEO.txt sin video = todavía no se puede preparar (se avisa y se sigue).

Historias (id <fecha>_h<orden>, ej. 2026-10-21_h2). Salen de la lista "historias" de dia.json
(orden, hora, archivo, sticker); si no hay dia.json, de los archivos historia-N_*.png|jpg|mp4 del paquete
(y de historias/), a la hora de hora.txt. La API no publica stickers ni comparte posteos, entonces:
  - "Compartir la publicación del día" → historia "Nuevo en el perfil" con la tapa del posteo (la arma
    _herramientas/historia_nuevo_en_perfil.py). Sale después del posteo y solo si el posteo salió.
  - Con sticker de link → se usa la variante <nombre>__auto.png ("El link está en el perfil") si existe,
    en el paquete o en disenos/historias/png/. Si no hay variante, no se prepara: va a mano.
  - Con encuesta, cuenta regresiva o caja de preguntas → no se prepara: va a mano.
  - El texto de la imagen se saca de su HTML (fuente/ o disenos/historias/) y lo revisa verificar.py.

Qué hace: copia los archivos a media/<id>/, pasa PNG a JPEG (calidad 95), arma la pieza y la
deja en cola.json como "borrador". Nunca toca una pieza ya publicada.
"""

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from comun import (AR, RAIZ, ahora, buscar, cargar_cola, fmt, guardar_cola, iso, leer_fecha, log, ordenar,
                   preparar_consola)

CARGA = RAIZ.parent / "2026-10-07" / "carga"
MEDIA = RAIZ / "media"
IMAGENES = (".png", ".jpg", ".jpeg")
VIDEOS = (".mp4", ".mov")
RE_PLACA = re.compile(r"^p?(\d{1,2})\.(png|jpe?g)$", re.I)
RE_HORA = re.compile(r"(?<![\d:])(\d{1,2})[:.](\d{2})(?![\d:])")
DISENOS_HIST = RAIZ.parent / "2026-10-07" / "disenos" / "historias"
HERRAMIENTAS = RAIZ.parent / "_herramientas"
RE_HIST_PAQUETE = re.compile(r"^historia-(\d{1,2})(?:_.*)?\.(png|jpe?g|mp4|mov)$", re.I)
RE_HIST_CARPETA = re.compile(r"^h?(\d{1,2})(?:_.*)?\.(png|jpe?g|mp4|mov)$", re.I)


class ErrorPaquete(Exception):
    """El paquete tiene un problema: hay que corregirlo."""


class SinFeed(Exception):
    """Ese día no hay nada para el feed (solo historias) o falta el video."""


# ---------------------------------------------------------------- lectura del paquete

def leer_ficha(carpeta):
    ficha = {}
    ruta = carpeta / "pieza.txt"
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8-sig").splitlines():
            if ":" in linea and not linea.lstrip().startswith("#"):
                k, v = linea.split(":", 1)
                ficha[k.strip().lower()] = v.strip()
    return ficha


def leer_pie(carpeta):
    ruta = carpeta / "pie.txt"
    if not ruta.exists():
        raise ErrorPaquete("falta pie.txt")
    pie = ruta.read_text(encoding="utf-8-sig").replace("\r\n", "\n").strip()
    if not pie:
        raise ErrorPaquete("pie.txt está vacío")
    return pie


def leer_hora(carpeta, ficha, fecha, hora_cli):
    if hora_cli:
        return hora_cli, "--hora"
    ruta = carpeta / "hora.txt"
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8-sig").splitlines():
            m = RE_HORA.search(linea)
            if m:
                return f"{m.group(1)}:{m.group(2)}", "hora.txt"
    if ficha.get("hora"):
        return ficha["hora"], "pieza.txt"
    h, _ = hora_del_plan(fecha)
    if h:
        return h, "plan.md"
    raise ErrorPaquete("no sé a qué hora sale: falta hora.txt (o usá --hora 20:30)")


def leer_alt(carpeta, nombres):
    """Devuelve una lista alineada con 'nombres' (placas) o un solo texto."""
    ruta = carpeta / "alt.txt"
    if not ruta.exists():
        return ""
    lineas = ruta.read_text(encoding="utf-8-sig").replace("\r\n", "\n").split("\n")
    por_placa, actual = {}, None
    for linea in lineas:
        m = re.match(r"^\s*(p?\d{1,2}\.(?:png|jpe?g))\s*[:.\-–]?\s*(.*)$", linea, re.I)
        if m:
            actual = m.group(1).lower()
            por_placa[actual] = m.group(2).strip()
        elif actual and linea.strip():
            por_placa[actual] = (por_placa[actual] + " " + linea.strip()).strip()
        elif actual and not linea.strip() and por_placa.get(actual):
            actual = None
    if por_placa:
        return [por_placa.get(n.lower(), "") for n in nombres]
    texto = [l.strip() for l in lineas if l.strip()
             and not re.match(r"^(texto alternativo|dónde se pega|donde se pega|fuente)\b", l.strip(), re.I)]
    return " ".join(texto)


def hora_del_plan(fecha):
    """Fila de ese día en carga/plan.md: '| **Mié 14/10** | 20:30 · carrusel 8 placas |'.
    Devuelve (hora, tipo); ("", "sin feed") si el plan dice que ese día no hay feed;
    (None, None) si el plan no tiene ese día."""
    plan = CARGA / "plan.md"
    if not plan.exists():
        return None, None
    for linea in plan.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*\**\s*\w+\s+(\d{1,2})/(\d{1,2})\s*\**\s*\|([^|]*)\|", linea)
        if not m or int(m.group(1)) != fecha.day or int(m.group(2)) != fecha.month:
            continue
        feed = m.group(3).strip()
        f = re.match(r"(\d{1,2}):(\d{2})\s*·\s*(carrusel|reel|imagen)", feed, re.I)
        if f:
            return f"{int(f.group(1)):02d}:{f.group(2)}", f.group(3).lower()
        return "", "sin feed"
    return None, None


def fecha_de(nombre, ficha):
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", ficha.get("fecha") or nombre)
    if not m:
        raise ErrorPaquete(f"no sé de qué día es '{nombre}' (la carpeta se llama como la fecha, ej. 2026-10-14)")
    return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=AR)


def archivos_del_feed(carpeta):
    placas = sorted((f for f in carpeta.iterdir() if f.is_file() and RE_PLACA.match(f.name)),
                    key=lambda f: int(RE_PLACA.match(f.name).group(1)))
    videos = sorted(f for f in carpeta.iterdir() if f.is_file() and f.suffix.lower() in VIDEOS
                    and not f.name.lower().startswith("plan-b"))
    videos.sort(key=lambda f: f.stem.lower() != "video")  # video.mp4 primero
    portadas = sorted(f for f in carpeta.iterdir() if f.is_file() and f.stem.lower() == "portada"
                      and f.suffix.lower() in IMAGENES)
    return placas, videos, (portadas[0] if portadas else None)


# ---------------------------------------------------------------- conversión

def a_jpeg(origen, destino):
    from PIL import Image

    with Image.open(origen) as im:
        icc = im.info.get("icc_profile")
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            im = im.convert("RGBA")
            fondo = Image.new("RGB", im.size, (255, 255, 255))
            fondo.paste(im, mask=im.split()[-1])
            im = fondo
            log(f"  aviso: {origen.name} tenía transparencia; quedó sobre fondo blanco")
        elif im.mode != "RGB":
            im = im.convert("RGB")
        if im.width > 1440:
            alto = round(im.height * 1080 / im.width)
            im = im.resize((1080, alto), Image.LANCZOS)
            log(f"  {origen.name} era más ancha que 1440 px: quedó en 1080×{alto}")
        extra = {"icc_profile": icc} if icc else {}
        im.save(destino, "JPEG", quality=95, subsampling=0, optimize=True, **extra)


# ---------------------------------------------------------------- armado

def origen_relativo(carpeta):
    """Ruta del paquete sin la parte de la compu (el repo es público)."""
    try:
        return carpeta.resolve().relative_to(RAIZ.parent.resolve()).as_posix()
    except ValueError:
        return carpeta.name


def preparar(carpeta, hora_cli=None, tipo_cli=None, ruta_cola=None):
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        raise ErrorPaquete(f"no existe la carpeta {carpeta}")
    id_ = carpeta.name
    ficha = leer_ficha(carpeta)
    fecha = fecha_de(id_, ficha)

    placas, videos, portada = archivos_del_feed(carpeta)
    _, tipo_plan = hora_del_plan(fecha)
    if tipo_plan == "sin feed" or (carpeta / "SOLO-HISTORIAS.txt").exists():
        if (placas or videos) and not (tipo_cli or ficha.get("tipo")):
            raise SinFeed("plan.md dice que este día no hay feed (el video o las placas son para historias). "
                          "Si igual va al feed, usá --tipo reel|carrusel|imagen.")
        if not (placas or videos):
            raise SinFeed("día sin publicación en el feed (solo historias)")
    if not placas and not videos:
        espera = carpeta / "ESPERA-VIDEO.txt"
        if espera.exists():
            falta_txt = next((l.strip(" -") for l in espera.read_text(encoding="utf-8-sig").splitlines()
                              if ".mp4" in l), "el video")
            raise SinFeed(f"espera el video ({falta_txt}). Cuando esté como video.mp4 en la carpeta, volvé a correr esto.")
        raise SinFeed("día sin publicación en el feed (solo historias)")

    tipo = (tipo_cli or ficha.get("tipo") or ("reel" if videos else None)
            or ("carrusel" if len(placas) > 1 else "imagen")).lower()
    if tipo_plan and tipo_plan not in (tipo, "sin feed"):
        log(f"  aviso: plan.md dice {tipo_plan} para este día y el paquete parece {tipo}")
    if tipo == "reel":
        if placas:
            raise ErrorPaquete(f"hay un video y además {len(placas)} placa(s) numeradas: ¿es reel o carrusel?")
        if len(videos) > 1:
            log(f"  aviso: hay {len(videos)} videos; uso {videos[0].name}")
    elif videos:
        raise ErrorPaquete("hay un video en un paquete de placas")

    hora, de_donde = leer_hora(carpeta, ficha, fecha, hora_cli)
    mh = re.match(r"^\s*(\d{1,2})[:.](\d{2})\s*$", hora)
    if not mh or int(mh.group(1)) > 23 or int(mh.group(2)) > 59:
        raise ErrorPaquete(f"la hora '{hora}' no se entiende (formato 20:30)")
    fecha_hora = fecha.replace(hour=int(mh.group(1)), minute=int(mh.group(2)))
    hora_plan, _ = hora_del_plan(fecha)
    if hora_plan and hora_plan != f"{fecha_hora:%H:%M}":
        log(f"  aviso: {de_donde} dice {fecha_hora:%H:%M} y plan.md dice {hora_plan}; uso {fecha_hora:%H:%M}")

    pie = leer_pie(carpeta)
    alt = leer_alt(carpeta, [p.name for p in placas]) if tipo != "reel" else leer_alt(carpeta, [])
    if isinstance(alt, list) and alt and len(set(alt)) == 1 and len(alt) > 1:
        alt = alt[0]

    piezas = cargar_cola(ruta_cola) if ruta_cola else cargar_cola()
    vieja = buscar(piezas, id_)
    if vieja and vieja.get("estado") == "publicado":
        raise ErrorPaquete(f"'{id_}' ya está publicada; no se vuelve a preparar")

    # media/<id>/ se rehace de cero
    destino = MEDIA / id_
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    rel = lambda p: p.relative_to(RAIZ).as_posix()

    nuevos, port_rel = [], None
    if tipo == "reel":
        v = destino / ("reel" + videos[0].suffix.lower())
        shutil.copy2(videos[0], v)
        nuevos.append(rel(v))
        if portada:
            pj = destino / "portada.jpg"
            a_jpeg(portada, pj)
            port_rel = rel(pj)
    else:
        for i, origen in enumerate(placas, 1):
            j = destino / f"p{i:02d}.jpg"
            a_jpeg(origen, j)
            nuevos.append(rel(j))

    pieza = {
        "id": id_,
        "fecha_hora": iso(fecha_hora),
        "tipo": tipo,
        "archivos": nuevos,
        "pie": pie,
        "alt": alt,
        "estado": "borrador",
        "resultado": None,
        "portada": port_rel,
        "intentos": 0,
        "origen": origen_relativo(carpeta),
    }
    if vieja:
        piezas[piezas.index(vieja)] = pieza
    else:
        piezas.append(pieza)
    ordenar(piezas)
    if ruta_cola:
        guardar_cola(piezas, ruta_cola)
    else:
        guardar_cola(piezas)
    return pieza, bool(vieja), de_donde


# ---------------------------------------------------------------- historias

STICKERS = (
    ("link", r"\blink\b|\benlace\b"),
    ("encuesta", r"\bencuesta\b"),
    ("cuenta regresiva", r"cuenta\s+regresiva"),
    ("caja de preguntas", r"caja\s+de\s+preguntas|sticker\s+\W?preguntas"),
    ("mención", r"sticker\s+de\s+menci[oó]n"),
)


class SinHistoria(Exception):
    """Esa historia no se puede publicar sola (sticker, falta el posteo, ya pasó…): va a mano o espera."""


def sticker_de(texto):
    """Qué sticker pide el plan (None si ninguno)."""
    t = (texto or "").strip()
    if not t or re.match(r"^(ninguno|sin sticker|no lleva)", t, re.I):
        return None
    for nombre, patron in STICKERS:
        if re.search(patron, t, re.I):
            return nombre
    if re.search(r"\ba mano\b", t, re.I):
        return "algo a mano"
    return None


def _hora_txt(texto):
    m = RE_HORA.search(texto or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def historias_del_paquete(carpeta):
    """[{orden, hora, archivo (Path o None), compartir, sticker, sticker_txt, texto_en_app}] del día."""
    salida = []
    dia = carpeta / "dia.json"
    if dia.exists():
        try:
            datos = json.loads(dia.read_text(encoding="utf-8-sig"))
        except ValueError as e:
            raise ErrorPaquete(f"dia.json no se puede leer ({e})")
        for i, h in enumerate(datos.get("historias") or [], 1):
            nombre = str(h.get("archivo") or "").strip()
            compartir = nombre.lower().startswith("compartir")
            salida.append({
                "orden": int(h.get("orden") or i),
                "hora": _hora_txt(h.get("hora")),
                "archivo": None if compartir or not nombre else carpeta / nombre,
                "compartir": compartir,
                "sticker": sticker_de(h.get("sticker")),
                "sticker_txt": (h.get("sticker") or "").strip(),
                "texto_en_app": (h.get("texto_en_app") or "").strip(),
            })
        return salida
    # sin dia.json: los archivos historia-N_*.png del paquete y los de historias/
    hora = None
    if (carpeta / "hora.txt").exists():
        hora = _hora_txt(next((l for l in (carpeta / "hora.txt").read_text(encoding="utf-8-sig").splitlines()
                               if RE_HORA.search(l)), ""))
    vistos = set()
    for base, patron in ((carpeta, RE_HIST_PAQUETE), (carpeta / "historias", RE_HIST_CARPETA)):
        if not base.is_dir():
            continue
        for f in sorted(base.iterdir()):
            m = patron.match(f.name)
            if not f.is_file() or not m or "__auto" in f.stem or int(m.group(1)) in vistos:
                continue
            vistos.add(int(m.group(1)))
            salida.append({"orden": int(m.group(1)), "hora": hora, "archivo": f, "compartir": False,
                           "sticker": None, "sticker_txt": "", "texto_en_app": ""})
    return sorted(salida, key=lambda h: h["orden"])


def _sufijo(stem):
    """'historia-4_oferta_h4' → 'oferta_h4'; 'h2_la-cuenta-a-mano' → 'la-cuenta-a-mano'; '2_2000-pruebas' → '2000-pruebas'."""
    return re.sub(r"^(historia-\d{1,2}_|h?\d{1,2}_)", "", stem, flags=re.I)


def variante_auto(archivo, fecha):
    """<nombre>__auto.png (sin sticker, 'El link está en el perfil') en el paquete o en disenos/historias/png."""
    archivo = Path(archivo)
    for ext in (".png", ".jpg", ".jpeg", ".mp4"):
        cand = archivo.with_name(archivo.stem + "__auto" + ext)
        if cand.is_file():
            return cand
    pngs = DISENOS_HIST / "png"
    if not pngs.is_dir():
        return None
    suf = _sufijo(archivo.stem)
    candidatos = [f for f in pngs.iterdir() if f.is_file() and f.stem.endswith("__auto")
                  and (f.stem[:-6] == suf or f.stem[:-6].endswith("_" + suf))]
    if not candidatos:
        return None
    candidatos.sort(key=lambda f: (not f.stem.startswith(f"{fecha:%Y-%m-%d}"), f.name))
    return candidatos[0]


_INDICE_PNG = None


def _huella(ruta):
    return hashlib.sha1(Path(ruta).read_bytes()).hexdigest()


def fuente_html(archivo, carpeta, fecha):
    """El HTML del que salió la imagen (para leer su texto), o None. Busca en fuente/ del paquete y en las
    carpetas de placas verticales (disenos/historias, destacadas y reels): por nombre o por ser copia exacta."""
    global _INDICE_PNG
    archivo = Path(archivo)
    carpetas = [d for d in (DISENOS_HIST, DISENOS_HIST.parent / "destacadas", DISENOS_HIST.parent / "reels")
                if d.is_dir()]
    for cand in [carpeta / "fuente" / (archivo.stem + ".html"), archivo.parent / "fuente" / (archivo.stem + ".html")] \
            + [d / (archivo.stem + ".html") for d in carpetas]:
        if cand.is_file():
            return cand
    if archivo.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        return None
    if _INDICE_PNG is None:  # copias exactas de <carpeta>/png/*.png → <carpeta>/<nombre>.html
        _INDICE_PNG = {}
        for d in carpetas:
            for f in sorted((d / "png").glob("*.png")):
                if (d / (f.stem + ".html")).is_file():
                    _INDICE_PNG.setdefault(_huella(f), []).append(d / (f.stem + ".html"))
    iguales = _INDICE_PNG.get(_huella(archivo)) or []
    if iguales:  # si hay copias idénticas, la que lleva la fecha del día
        return next((f for f in iguales if f"{fecha:%Y-%m-%d}" in f.stem), iguales[0])
    suf = _sufijo(archivo.stem)
    cands = sorted(f for d in carpetas for f in d.glob("*.html") if not f.name.startswith("_")
                   and (f.stem == suf or f.stem.endswith("_" + suf)))
    if len(cands) == 1:
        return cands[0]
    del_dia = [f for f in cands if f.stem.startswith(f"{fecha:%Y-%m-%d}")]
    return del_dia[0] if len(del_dia) == 1 else None


class _Texto(HTMLParser):
    BLOQUES = {"p", "div", "br", "li", "h1", "h2", "h3", "span", "main", "figure"}
    OCULTOS = {"style", "script", "head", "title"}

    def __init__(self):
        super().__init__()
        self.partes, self.ocultos = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.OCULTOS:
            self.ocultos += 1
        elif tag in self.BLOQUES:
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in self.OCULTOS and self.ocultos:
            self.ocultos -= 1

    def handle_data(self, data):
        if not self.ocultos:
            self.partes.append(data)


def texto_de_html(ruta):
    """El texto visible de una placa HTML (sin estilos, comentarios ni título)."""
    lector = _Texto()
    lector.feed(Path(ruta).read_text(encoding="utf-8-sig"))
    lineas = (re.sub(r"\s+", " ", l).strip() for l in "".join(lector.partes).split("\n"))
    return "\n".join(l for l in lineas if l)


def _herramienta_nuevo():
    ruta = HERRAMIENTAS / "historia_nuevo_en_perfil.py"
    if not ruta.exists():
        raise SinHistoria(f"falta {ruta} (arma la historia 'Nuevo en el perfil')")
    spec = importlib.util.spec_from_file_location("historia_nuevo_en_perfil", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def posteo_del_dia(piezas, carpeta, fecha):
    """La pieza del feed de ese paquete que está en la cola (id = nombre de la carpeta), o None.
    Tiene que haber salido de este paquete (campo origen): la tapa y el título de "Nuevo en el perfil"
    salen del paquete, y anunciar otro posteo del mismo día mostraría algo que no está en el perfil."""
    origen = origen_relativo(carpeta)
    feed = [p for p in piezas if p.get("tipo") != "historia" and p.get("origen", origen) == origen]
    for p in feed:
        if str(p.get("id")) == carpeta.name:
            return p
    for p in feed:
        try:
            if str(p.get("id")).startswith(carpeta.name + "_") and leer_fecha(p["fecha_hora"]).date() == fecha.date():
                return p
        except Exception:
            continue
    return None


def _tapa_de_cola(pieza):
    rels = [pieza.get("portada")] if pieza.get("tipo") == "reel" else list(pieza.get("archivos") or [])[:1]
    for rel in rels:
        if rel and (RAIZ / rel).is_file():
            return RAIZ / rel
    return None


def armar_historia(destino, *, archivo=None, render=None):
    """Copia (o renderiza) el archivo de la historia a media/<id>/ y devuelve su ruta relativa al repo.
    Si hay que renderizar, se renderiza antes de borrar lo que había (si falla, media/<id>/ queda igual)."""
    tmp = None
    try:
        if render:
            tmp = destino.with_name(destino.name + "__render.png")
            render(tmp)
            archivo = tmp
        archivo = Path(archivo)
        ext = archivo.suffix.lower()
        if ext not in VIDEOS + IMAGENES:
            raise ErrorPaquete(f"{archivo.name}: una historia es una imagen (PNG/JPG) o un video (.mp4/.mov)")
        if destino.exists():
            shutil.rmtree(destino)
        destino.mkdir(parents=True)
        if ext in VIDEOS:
            final = destino / ("historia" + ext)
            shutil.copy2(archivo, final)
        else:
            final = destino / "historia.jpg"
            a_jpeg(archivo, final)
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
    return final.relative_to(RAIZ).as_posix()


def pieza_historia(id_, fecha_hora, orden, rel, texto, origen, **extra):
    pieza = {
        "id": id_,
        "fecha_hora": iso(fecha_hora),
        "tipo": "historia",
        "archivos": [rel],
        "pie": "",
        "alt": "",
        "estado": "borrador",
        "resultado": None,
        "portada": None,
        "intentos": 0,
        "origen": origen,
        "orden": orden,
        "texto": texto or "",
    }
    pieza.update({k: v for k, v in extra.items() if v})
    return pieza


def preparar_historias(carpeta, piezas, momento, saltar_aprobadas=False):
    """Arma las historias del paquete en 'piezas' (la cola en memoria).
    Devuelve (hechas: [(pieza, rehecha)], saltadas: [texto], errores: [texto])."""
    carpeta = Path(carpeta)
    ficha = leer_ficha(carpeta)
    fecha = fecha_de(carpeta.name, ficha)
    hechas, saltadas, errores = [], [], []
    for h in historias_del_paquete(carpeta):
        id_ = f"{carpeta.name}_h{h['orden']}"
        etiqueta = f"historia {h['orden']}"
        try:
            vieja = buscar(piezas, id_)
            if vieja and vieja.get("estado") == "publicado":
                raise SinHistoria("ya está publicada")
            if vieja and saltar_aprobadas and vieja.get("estado") == "aprobado":
                raise SinHistoria(f"ya está aprobada (para rehacerla: python preparar.py {carpeta.name})")
            hora = h["hora"]
            if not hora:
                try:
                    hora, _ = leer_hora(carpeta, ficha, fecha, None)
                except ErrorPaquete:
                    raise ErrorPaquete("no sé a qué hora sale (falta la hora en dia.json y hora.txt)")
            mh = re.match(r"^\s*(\d{1,2})[:.](\d{2})\s*$", hora)
            fecha_hora = fecha.replace(hour=int(mh.group(1)), minute=int(mh.group(2)))
            extra, notas = {}, []

            if h["compartir"]:
                posteo = posteo_del_dia(piezas, carpeta, fecha)
                if not posteo:
                    raise SinHistoria("es 'Compartir la publicación del día' y el posteo de este paquete no está en "
                                      "la cola (todavía). Cuando esté, volvé a correr esto")
                if leer_fecha(posteo["fecha_hora"]) > fecha_hora:
                    fecha_hora = leer_fecha(posteo["fecha_hora"])
                if fecha_hora <= momento:
                    raise SinHistoria(f"su hora ya pasó ({fmt(fecha_hora)})")
                herr = _herramienta_nuevo()
                tapa = herr.tapa_de_paquete(carpeta) or _tapa_de_cola(posteo)
                if not tapa:
                    raise ErrorPaquete("no encuentro la tapa del posteo (01.png o portada.png)")
                titulo = herr.titulo_de_paquete(carpeta)
                datos = {}

                def render(salida, tapa=tapa, titulo=titulo, datos=datos):
                    try:
                        datos.update(herr.renderizar(tapa, titulo, salida))
                    except ImportError as e:
                        raise SinHistoria(f"para armar 'Nuevo en el perfil' hace falta Playwright ({e})")
                    except OSError:
                        raise
                    except Exception as e:  # sin internet (sin la letra Inter), tapa que no carga, Playwright…
                        raise SinHistoria(f"no se pudo armar 'Nuevo en el perfil': {e}. Volvé a correr esto con internet")

                rel = armar_historia(MEDIA / id_, render=render)
                texto = datos.get("texto") or herr.texto_de(titulo)
                extra["depende_de"] = posteo["id"]
                notas.append(f"'Nuevo en el perfil' con la tapa de {posteo['id']} (la API no comparte el posteo)")
                if h["texto_en_app"]:
                    notas.append(f"texto del plan: {h['texto_en_app'][:80]}")
            else:
                archivo = h["archivo"]
                if archivo is None or not archivo.is_file():
                    raise ErrorPaquete(f"no existe el archivo {archivo.name if archivo else '(sin nombre)'}")
                if fecha_hora <= momento:
                    raise SinHistoria(f"su hora ya pasó ({fmt(fecha_hora)})")
                if h["sticker"]:
                    auto = variante_auto(archivo, fecha)
                    if not auto:
                        raise SinHistoria(f"lleva {h['sticker']} y la API no publica stickers: va a mano "
                                          f"({archivo.name}). Para que salga sola, hacé {archivo.stem}__auto.png "
                                          "sin sticker")
                    notas.append(f"sin sticker: usa {auto.name} en lugar de {archivo.name} ({h['sticker']} → "
                                 "el pedido va impreso en la imagen)")
                    archivo = auto
                if re.search(r"\belegir\b", h["sticker_txt"], re.I):
                    notas.append("el plan pide elegir entre varias (la de más envíos): se preparó "
                                 f"{archivo.name}. Para otra: python preparar.py historia <archivo> --fecha "
                                 f"{fecha:%Y-%m-%d} --hora {fecha_hora:%H:%M} --orden {h['orden']}")
                fuente = fuente_html(archivo, carpeta, fecha)
                texto = texto_de_html(fuente) if fuente else ""
                if not fuente:
                    notas.append("no encontré el HTML de la imagen: el texto no se revisó solo")
                rel = armar_historia(MEDIA / id_, archivo=archivo)
                extra["fuente"] = origen_relativo(fuente) if fuente else None

            pieza = pieza_historia(id_, fecha_hora, h["orden"], rel, texto, origen_relativo(carpeta),
                                   nota=" · ".join(notas), **extra)
            if vieja:
                piezas[piezas.index(vieja)] = pieza
            else:
                piezas.append(pieza)
            hechas.append((pieza, bool(vieja)))
        except SinHistoria as e:
            saltadas.append(f"{id_} ({etiqueta}): {e}")
        except (ErrorPaquete, OSError) as e:
            errores.append(f"{id_} ({etiqueta}): {e}")
    return hechas, saltadas, errores


def historia_suelta(args, momento):
    """python preparar.py historia ARCHIVO --fecha … --hora … [--orden N] [--id ID] [--depende-de ID]."""
    archivo = Path(args.archivo or "")
    if not archivo.is_file():
        print(f"No existe el archivo '{args.archivo}'.")
        return 1
    if not args.fecha or not args.hora:
        print("Faltan --fecha 2026-10-21 y --hora 08:30.")
        return 1
    try:
        fecha = fecha_de(args.fecha, {})
    except ErrorPaquete as e:
        print(f"NO se preparó: {e}")
        return 1
    mh = re.match(r"^\s*(\d{1,2})[:.](\d{2})\s*$", args.hora)
    if not mh or int(mh.group(1)) > 23 or int(mh.group(2)) > 59:
        print(f"La hora '{args.hora}' no se entiende (formato 20:30).")
        return 1
    fecha_hora = fecha.replace(hour=int(mh.group(1)), minute=int(mh.group(2)))
    ruta_cola = args.cola
    piezas = cargar_cola(ruta_cola) if ruta_cola else cargar_cola()
    del_dia = [int(p.get("orden") or 0) for p in piezas if p.get("tipo") == "historia"
               and str(p.get("id")).startswith(f"{fecha:%Y-%m-%d}")]
    orden = args.orden or (max(del_dia) + 1 if del_dia else 1)
    id_ = args.id or f"{fecha:%Y-%m-%d}_h{orden}"
    vieja = buscar(piezas, id_)
    if vieja and vieja.get("estado") == "publicado":
        print(f"'{id_}' ya está publicada; no se vuelve a preparar.")
        return 1
    if args.depende_de and not buscar(piezas, args.depende_de):
        print(f"--depende-de {args.depende_de}: esa pieza no está en la cola.")
        return 1
    fuente = fuente_html(archivo, archivo.parent, fecha)
    texto = args.texto or (texto_de_html(fuente) if fuente else "")
    try:
        rel = armar_historia(MEDIA / id_, archivo=archivo)
    except ErrorPaquete as e:
        print(f"NO se preparó: {e}")
        return 1
    pieza = pieza_historia(id_, fecha_hora, orden, rel, texto, origen_relativo(archivo.parent),
                           depende_de=args.depende_de, fuente=origen_relativo(fuente) if fuente else None)
    if vieja:
        piezas[piezas.index(vieja)] = pieza
    else:
        piezas.append(pieza)
    ordenar(piezas)
    guardar_cola(piezas, ruta_cola) if ruta_cola else guardar_cola(piezas)

    from verificar import validar_pieza
    print(f"== {id_}\n  {'rehecha (volvió a borrador)' if vieja else 'sumada como borrador'}: historia · "
          f"{fmt(fecha_hora)} · orden {orden} · {rel}")
    if fecha_hora <= momento:
        print("  aviso  su hora ya pasó: así no va a salir")
    err, av = validar_pieza(pieza, momento)
    for e in err:
        print(f"  ERROR  {e}")
    for a in av:
        print(f"  aviso  {a}")
    if not err:
        print(f"\nPara que salga: python aprobar.py {id_}   (y después Commit + Push)")
    return 1 if err else 0


def main():
    preparar_consola()
    ap = argparse.ArgumentParser(description="Suma piezas del feed e historias a cola.json como borrador.")
    ap.add_argument("paquete", help="fecha (2026-10-14), ruta a la carpeta, 'todo' o 'historia'")
    ap.add_argument("archivo", nargs="?", help="con 'historia': la imagen (PNG/JPG 1080×1920) o el video vertical")
    ap.add_argument("--hora", help="hora de publicación, ej. 20:30 (feed; con 'historia', la de la historia)")
    ap.add_argument("--tipo", choices=("carrusel", "imagen", "reel"))
    ap.add_argument("--fecha", help="con 'historia': el día, ej. 2026-10-21")
    ap.add_argument("--orden", type=int, help="con 'historia': su lugar entre las de esa hora (1, 2, 3…)")
    ap.add_argument("--id", help="con 'historia': otro id (por defecto <fecha>_h<orden>)")
    ap.add_argument("--depende-de", help="con 'historia': sale solo si ya salió esta pieza del feed")
    ap.add_argument("--texto", help="con 'historia': el texto que tiene la imagen (si no, se busca su HTML)")
    ap.add_argument("--sin-historias", action="store_true", help="solo el feed")
    ap.add_argument("--solo-historias", action="store_true", help="solo las historias")
    ap.add_argument("--carga", help="otra carpeta carga/ (por defecto ../2026-10-07/carga)")
    ap.add_argument("--cola", help="otra cola.json (para pruebas)")
    ap.add_argument("--media", help="otra carpeta para los archivos, dentro del repo (para pruebas, ej. _prueba/media)")
    args = ap.parse_args()

    global CARGA, MEDIA
    if args.carga:
        CARGA = Path(args.carga)
    if args.media:
        MEDIA = (RAIZ / args.media).resolve() if not Path(args.media).is_absolute() else Path(args.media).resolve()
        try:
            MEDIA.relative_to(RAIZ)
        except ValueError:
            print("--media tiene que ser una carpeta dentro del repo (Instagram baja los archivos de ahí).")
            return 1
    momento = ahora()

    if args.paquete.lower() == "historia":
        return historia_suelta(args, momento)

    todo = args.paquete.lower() == "todo"
    if todo:
        carpetas = sorted(c for c in CARGA.iterdir() if c.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}", c.name)) \
            if CARGA.exists() else []
        if not carpetas:
            print(f"No hay paquetes en {CARGA} (carpetas con nombre de fecha, ej. 2026-10-14).")
            return 1
    else:
        c = Path(args.paquete)
        if not c.is_dir():
            c = CARGA / args.paquete
        if not c.is_dir():
            hay = sorted(x.name for x in CARGA.iterdir() if x.is_dir()) if CARGA.exists() else []
            print(f"No encuentro el paquete '{args.paquete}' en {CARGA}.")
            print("Paquetes que hay: " + (", ".join(hay) if hay else "ninguno todavía"))
            return 1
        carpetas = [c]

    from verificar import validar_pieza

    ya = {str(p.get("id")): p.get("estado") for p in (cargar_cola(args.cola) if args.cola else cargar_cola())}
    errores, listas, saltadas = 0, [], []
    for carpeta in carpetas:
        print(f"\n== {carpeta.name}")
        # ---- feed (como siempre)
        if not args.solo_historias:
            if todo and ya.get(carpeta.name) in ("aprobado", "publicado"):
                saltadas.append(f"{carpeta.name}: ya está {ya[carpeta.name]} (para rehacerla: python preparar.py {carpeta.name})")
            else:
                try:
                    pieza, rehecha, de_donde = preparar(carpeta, args.hora, args.tipo, args.cola)
                except SinFeed as e:
                    saltadas.append(f"{carpeta.name}: {e}")
                    pieza = None
                except ErrorPaquete as e:
                    print(f"  feed NO se preparó: {e}")
                    errores += 1
                    pieza = None
                if pieza:
                    accion = "rehecha (volvió a borrador)" if rehecha else "sumada como borrador"
                    print(f"  {accion}: {pieza['tipo']} · {fmt(pieza['fecha_hora'])} (hora de {de_donde}) · "
                          f"{len(pieza['archivos'])} archivo(s)" + (" + portada" if pieza.get("portada") else ""))
                    err, av = validar_pieza(pieza)
                    for e in err:
                        print(f"  ERROR  {e}")
                    for a in av:
                        print(f"  aviso  {a}")
                    errores += len(err)
                    if not err:
                        listas.append(pieza["id"])

        # ---- historias
        if args.sin_historias:
            continue
        piezas = cargar_cola(args.cola) if args.cola else cargar_cola()
        try:
            hechas, salt_h, err_h = preparar_historias(carpeta, piezas, momento, saltar_aprobadas=todo)
        except ErrorPaquete as e:
            hechas, salt_h, err_h = [], [], [f"{carpeta.name}: {e}"]
        if hechas:
            ordenar(piezas)
            guardar_cola(piezas, args.cola) if args.cola else guardar_cola(piezas)
        for pieza, rehecha in hechas:
            accion = "rehecha (volvió a borrador)" if rehecha else "sumada como borrador"
            print(f"  {pieza['id']}: {accion}: historia {pieza['orden']} · {fmt(pieza['fecha_hora'])}"
                  + (f" · después de {pieza['depende_de']}" if pieza.get("depende_de") else ""))
            if pieza.get("nota"):
                print(f"      nota   {pieza['nota']}")
            err, av = validar_pieza(pieza, momento)
            for e in err:
                print(f"      ERROR  {e}")
            for a in av:
                print(f"      aviso  {a}")
            errores += len(err)
            if not err:
                listas.append(pieza["id"])
        for e in err_h:
            print(f"  historia NO se preparó: {e}")
        errores += len(err_h)
        saltadas.extend(salt_h)

    if saltadas:
        print("\nNo van a la cola (por ahora):")
        for s_ in saltadas:
            print(f"  - {s_}")
    print()
    if listas:
        dias = sorted({i[:10] for i in listas})
        print("Para que salgan: python aprobar.py " + (listas[0] if len(listas) == 1 else
              (dias[0] + "   (feed e historias de ese día)" if len(dias) == 1 else
               "semana   (o un día: python aprobar.py 2026-10-14; o una sola: python aprobar.py 2026-10-21_h2)")))
        print("Y después: GitHub Desktop → Commit → Push origin (si no, GitHub no se entera).")
    if errores:
        print("Hay errores: corregí el paquete y volvé a correr preparar.py (lo que tiene errores no se puede aprobar).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
