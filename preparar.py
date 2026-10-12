"""Suma una pieza del feed a cola.json como "borrador", a partir de su paquete de carga.

Uso:
  python preparar.py 2026-10-14            usa ../2026-10-07/carga/2026-10-14/
  python preparar.py "C:/ruta/al/paquete"  cualquier carpeta con el mismo formato
  python preparar.py todo                  todos los paquetes de carga/ (salta los días de solo
                                           historias, los que esperan video y lo ya aprobado)
  Opciones: --hora 20:30  --tipo carrusel|imagen|reel  --carga RUTA  --cola RUTA

El paquete es la carpeta del día (ej. carga/2026-10-14/), tal como la arma el equipo:
  - Placas del feed: 01.png, 02.png... en ese orden (carrusel; una sola = imagen).
  - Reel: video.mp4 (o cualquier .mp4/.mov que no empiece con "plan-b") y portada.png.
  - pie.txt: el pie tal cual.
  - hora.txt: la primera hora que aparezca (ej. "Miércoles 14/10/2026 · 20:30", "08:30").
    Si no hay, se usa pieza.txt ("hora: 20:30") o la tabla de carga/plan.md.
  - alt.txt: "01.png: texto" (o "01.png" y el texto abajo), uno por placa.
    Si no tiene nombres de placa, todo el texto vale para la pieza.
  - Se ignoran: historias/, historia-*.png, plan-b_*, *.md, FIJAR.txt y demás notas.
  - ESPERA-VIDEO.txt sin video = todavía no se puede preparar (se avisa y se sigue).

Qué hace: copia los archivos a media/<id>/, pasa PNG a JPEG (calidad 95), arma la pieza y la
deja en cola.json como "borrador". Nunca toca una pieza ya publicada.
"""

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from comun import (AR, RAIZ, buscar, cargar_cola, fmt, guardar_cola, iso, log, ordenar,
                   preparar_consola)

CARGA = RAIZ.parent / "2026-10-07" / "carga"
MEDIA = RAIZ / "media"
IMAGENES = (".png", ".jpg", ".jpeg")
VIDEOS = (".mp4", ".mov")
RE_PLACA = re.compile(r"^p?(\d{1,2})\.(png|jpe?g)$", re.I)
RE_HORA = re.compile(r"(?<![\d:])(\d{1,2})[:.](\d{2})(?![\d:])")


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
            raise SinFeed("día sin publicación en el feed (solo historias, que se suben a mano)")
    if not placas and not videos:
        espera = carpeta / "ESPERA-VIDEO.txt"
        if espera.exists():
            falta_txt = next((l.strip(" -") for l in espera.read_text(encoding="utf-8-sig").splitlines()
                              if ".mp4" in l), "el video")
            raise SinFeed(f"espera el video ({falta_txt}). Cuando esté como video.mp4 en la carpeta, volvé a correr esto.")
        raise SinFeed("día sin publicación en el feed (solo historias, que se suben a mano)")

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


def main():
    preparar_consola()
    ap = argparse.ArgumentParser(description="Suma una pieza del feed a cola.json como borrador.")
    ap.add_argument("paquete", help="fecha (2026-10-14), ruta a la carpeta, o 'todo'")
    ap.add_argument("--hora", help="hora de publicación, ej. 20:30 (si no, la de hora.txt)")
    ap.add_argument("--tipo", choices=("carrusel", "imagen", "reel"))
    ap.add_argument("--carga", help="otra carpeta carga/ (por defecto ../2026-10-07/carga)")
    ap.add_argument("--cola", help="otra cola.json (para pruebas)")
    args = ap.parse_args()

    global CARGA
    if args.carga:
        CARGA = Path(args.carga)

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
        if todo and ya.get(carpeta.name) in ("aprobado", "publicado"):
            saltadas.append(f"{carpeta.name}: ya está {ya[carpeta.name]} (para rehacerla: python preparar.py {carpeta.name})")
            continue
        try:
            pieza, rehecha, de_donde = preparar(carpeta, args.hora, args.tipo, args.cola)
        except SinFeed as e:
            saltadas.append(f"{carpeta.name}: {e}")
            continue
        except ErrorPaquete as e:
            print(f"\n== {carpeta.name}\n  NO se preparó: {e}")
            errores += 1
            continue
        print(f"\n== {carpeta.name}")
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

    if saltadas:
        print("\nNo van a la cola (por ahora):")
        for s in saltadas:
            print(f"  - {s}")
    print()
    if listas:
        print("Para que salgan: python aprobar.py " + (listas[0] if len(listas) == 1 else "semana   (o una por una: python aprobar.py 2026-10-14)"))
        print("Y después: GitHub Desktop → Commit → Push origin (si no, GitHub no se entera).")
    if errores:
        print("Hay errores: corregí el paquete y volvé a correr preparar.py (lo que tiene errores no se puede aprobar).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
