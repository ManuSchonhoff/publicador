"""Publica en Instagram lo aprobado cuya hora ya pasó (API oficial, graph.instagram.com):
carruseles, imágenes, reels e historias (media_type=STORIES, imagen o video, sin stickers).

Lo corre GitHub cada 15 minutos. También se puede correr a mano.

Variables de entorno (en GitHub son secretos; nunca se imprimen):
  IG_TOKEN        token largo de la cuenta (permisos instagram_business_basic e
                  instagram_business_content_publish)
  IG_USER_ID      id de la cuenta de Instagram
  MEDIA_BASE_URL  de dónde baja Instagram los archivos: el "raw" del repo público,
                  ej. https://raw.githubusercontent.com/USUARIO/trackear-instagram/main/
  IG_API_VERSION  opcional (por defecto v23.0)

Uso:
  python publicar.py                publica lo que toca
  python publicar.py --solo-probar  no publica nada: revisa la cola, el token y que los
                                    archivos se puedan bajar, y dice qué publicaría
  python publicar.py --hay-algo     sin internet: dice si hay algo para publicar ahora
  python publicar.py --esperar 330  si hay algo aprobado en los próximos 330 min (y nada vencido),
                                    espera hasta su hora (GitHub no corre el cron cada 15 min de verdad)
  python publicar.py --seguir 90    después de publicar, si lo próximo aprobado sale dentro de 90 min
                                    (por ejemplo historias a las 20:35 y 20:40), espera y lo publica también
  --cola RUTA                       otra cola.json (solo con --solo-probar, --hay-algo o --esperar: pruebas)

Varias piezas a la misma hora salen en orden: primero el feed y después las historias (1, 2, 3…).
Una historia "Nuevo en el perfil" (campo depende_de) sale solo si ya salió el posteo que anuncia.
Tope propio: LIMITE_24H publicaciones en 24 h corridas (25; las historias cuentan). Lo que pasa el tope
espera a la próxima corrida.
"""

import argparse
import os
import sys
import time
from urllib.parse import quote

import copy
from pathlib import Path

from comun import (COLA, LIMITE_24H, Candado, ahora, buscar, cargar_cola, fmt, guardar_cola, leer_fecha,
                   limpiar, log, normalizar, pendientes_que_tocan, preparar_consola, publicadas_en_24h,
                   registrar, vencida)

VERSION = os.environ.get("IG_API_VERSION", "v23.0").strip() or "v23.0"
API = f"https://graph.instagram.com/{VERSION}"
MAX_INTENTOS_POR_PIEZA = 3          # corridas que se reintenta antes de quedar en "error"
ESPERA_REINTENTO = (5, 20, 60)      # segundos entre reintentos dentro de una misma llamada
CODIGOS_TRANSITORIOS = {1, 2, 4, 17, 32, 341, 368, 613, -1, -2}
VIDEOS = (".mp4", ".mov")


class ErrorAPI(Exception):
    def __init__(self, mensaje, transitorio=False, codigo=None):
        super().__init__(limpiar(mensaje))
        self.transitorio = transitorio
        self.codigo = codigo


# ---------------------------------------------------------------- llamadas

class Instagram:
    def __init__(self, token, user_id):
        import requests  # solo acá, para que --hay-algo no necesite nada instalado
        self.r = requests
        self.token = token
        self.user = user_id

    def llamar(self, metodo, ruta, datos=None, reintentar=True, antes_de_reintentar=None):
        """GET/POST a graph.instagram.com con reintentos. Nunca muestra el token."""
        url = f"{API}/{ruta.lstrip('/')}"
        datos = dict(datos or {})
        datos["access_token"] = self.token
        esperas = list(ESPERA_REINTENTO) if reintentar else []
        while True:
            try:
                if metodo == "GET":
                    resp = self.r.get(url, params=datos, timeout=60)
                else:
                    resp = self.r.post(url, data=datos, timeout=120)
                try:
                    cuerpo = resp.json()
                except ValueError:
                    cuerpo = {}
                if resp.ok and "error" not in cuerpo:
                    return cuerpo
                err = cuerpo.get("error", {}) if isinstance(cuerpo, dict) else {}
                codigo = err.get("code")
                msj = err.get("error_user_msg") or err.get("message") or resp.text[:300]
                sub = err.get("error_subcode")
                transitorio = resp.status_code >= 500 or codigo in CODIGOS_TRANSITORIOS or bool(err.get("is_transient"))
                fallo = ErrorAPI(f"Instagram respondió {resp.status_code}: {msj}"
                                 + (f" (código {codigo}" + (f"/{sub}" if sub else "") + ")" if codigo else ""),
                                 transitorio, codigo)
            except (self.r.ConnectionError, self.r.Timeout) as e:
                fallo = ErrorAPI(f"no hubo respuesta de Instagram ({type(e).__name__})", True)
            if not fallo.transitorio or not esperas:
                raise fallo
            espera = esperas.pop(0)
            log(f"  {fallo} → reintento en {espera} s")
            time.sleep(espera)
            if antes_de_reintentar:
                ya = antes_de_reintentar()
                if ya:
                    return ya

    def esperar_listo(self, contenedor, maximo_seg, cada_seg):
        fin = time.time() + maximo_seg
        while True:
            est = self.llamar("GET", contenedor, {"fields": "status_code,status"})
            codigo = est.get("status_code")
            if codigo in ("FINISHED", "PUBLISHED"):
                return
            if codigo in ("ERROR", "EXPIRED"):
                raise ErrorAPI(f"Instagram no pudo procesar el archivo: {codigo} · {est.get('status', '')}")
            if time.time() > fin:
                raise ErrorAPI(f"Instagram sigue procesando después de {maximo_seg // 60} min ({codigo})", True)
            time.sleep(cada_seg)

    def contenedor_publicado(self, contenedor, estricto=False):
        """Si ese contenedor ya figura PUBLISHED (salió aunque no nos llegó la respuesta), lo dice.
        Sirve para todo, y es lo único que evita duplicar una historia (no tienen pie para comparar).
        estricto (antes de crear un contenedor nuevo): si Instagram no contesta, no se sabe si salió;
        en vez de arriesgar una historia repetida, falla como pasajero y se reintenta en la próxima corrida."""
        if not contenedor:
            return None
        try:
            est = self.llamar("GET", contenedor, {"fields": "status_code"}, reintentar=estricto)
        except ErrorAPI as e:
            if estricto and e.transitorio:
                raise ErrorAPI(f"no pude mirar si el contenedor guardado ya salió ({e}); "
                               "no armo otro para no repetirla", True)
            return None
        if est.get("status_code") == "PUBLISHED":
            return {"id": None, "permalink": None, "por_contenedor": True}
        return None

    def cupo(self):
        """Publicaciones por API en las últimas 24 h según Instagram (None si no se pudo leer)."""
        try:
            r = self.llamar("GET", f"{self.user}/content_publishing_limit",
                            {"fields": "quota_usage,config"}, reintentar=False)
            return int((r.get("data") or [{}])[0].get("quota_usage") or 0)
        except (ErrorAPI, ValueError, TypeError):
            return None

    def recientes(self):
        r = self.llamar("GET", f"{self.user}/media",
                        {"fields": "id,caption,timestamp,permalink,media_type", "limit": 25})
        return r.get("data", [])

    def ya_publicada(self, pieza):
        """Si ya hay en la cuenta un posteo con el mismo pie, devuelve sus datos (evita duplicados)."""
        objetivo = normalizar(pieza["pie"])
        desde = leer_fecha(pieza["fecha_hora"]).timestamp() - 6 * 3600
        for m in self.recientes():
            try:
                ts = leer_fecha(m.get("timestamp", "").replace("+0000", "+00:00")).timestamp()
            except Exception:
                ts = desde
            if ts >= desde and normalizar(m.get("caption")) == objetivo:
                return {"id": m["id"], "permalink": m.get("permalink")}
        return None

    def crear(self, datos):
        return self.llamar("POST", f"{self.user}/media", datos)["id"]

    def subir_video_directo(self, datos, rel):
        """Subida resumable: se crea el contenedor sin video_url y se manda el archivo a rupload."""
        from comun import RAIZ
        ruta = RAIZ / rel
        datos = {k: v for k, v in datos.items() if k != "video_url"}
        datos["upload_type"] = "resumable"
        r = self.llamar("POST", f"{self.user}/media", datos)
        cont = r["id"]
        uri = r.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{VERSION}/{cont}"
        tam = ruta.stat().st_size
        with open(ruta, "rb") as f:
            resp = self.r.post(uri, data=f, timeout=600,
                               headers={"Authorization": f"OAuth {self.token}", "offset": "0",
                                        "file_size": str(tam), "Content-Type": "application/octet-stream"})
        if not resp.ok:
            raise ErrorAPI(f"la subida directa del video falló: {resp.status_code} {resp.text[:200]}")
        log(f"  video subido directo ({tam / 1e6:.1f} MB)")
        return cont

    def crear_imagen(self, datos, alt):
        """Con texto alternativo; si la API no lo acepta, sin él (y lo avisa)."""
        if alt:
            try:
                return self.crear(dict(datos, alt_text=alt[:1000]))
            except ErrorAPI as e:
                if "alt_text" not in str(e) and e.codigo != 100:
                    raise
                log(f"  aviso: Instagram no aceptó el texto alternativo ({e}); sigo sin él")
        return self.crear(datos)


# ---------------------------------------------------------------- publicación

def url_publica(base, rel):
    return base.rstrip("/") + "/" + quote(rel.replace("\\", "/"))


def comprobar_urls(ig, base, rels):
    for rel in rels:
        url = url_publica(base, rel)
        try:
            r = ig.r.head(url, allow_redirects=True, timeout=30)
            ok = r.status_code == 200
            detalle = f"HTTP {r.status_code}"
        except Exception as e:
            ok, detalle = False, type(e).__name__
        if not ok:
            raise ErrorAPI(f"no se puede bajar {rel} desde GitHub ({detalle}). ¿Está subido (Push) y el repo es público?", True)


def alts_de(pieza, n):
    alt = pieza.get("alt")
    if isinstance(alt, list):
        return alt if len(alt) == n else [alt[0] if alt else ""] * n
    return [alt or ""] * n


def es_video(rel):
    return Path(str(rel)).suffix.lower() in VIDEOS


def describir(pieza, base=""):
    """Qué llamadas haría la publicación (para --solo-probar)."""
    tipo, archivos = pieza.get("tipo"), pieza.get("archivos") or []
    url = (lambda rel: url_publica(base, rel)) if base else (lambda rel: rel)
    if tipo == "historia" and archivos:
        clase = "video_url" if es_video(archivos[0]) else "image_url"
        return f"contenedor STORIES ({clase} {url(archivos[0])}), sin pie → esperar FINISHED → media_publish"
    if tipo == "reel" and archivos:
        return f"contenedor REELS (video_url {url(archivos[0])}) → esperar FINISHED → media_publish"
    if tipo == "carrusel":
        return f"{len(archivos)} placas + contenedor CAROUSEL → media_publish"
    if tipo == "imagen" and archivos:
        return f"contenedor de imagen ({url(archivos[0])}) → media_publish"
    return f"tipo {tipo}"


def publicar_pieza(ig, base, pieza, al_crear=None):
    """Publica una pieza. al_crear() se llama cuando ya hay contenedor (para guardarlo en la cola
    antes de media_publish: si la respuesta se pierde, la próxima corrida no la repite)."""
    tipo, pie, archivos = pieza["tipo"], pieza["pie"], pieza["archivos"]
    comprobar_urls(ig, base, archivos + ([pieza["portada"]] if pieza.get("portada") and tipo != "historia" else []))

    def anotar(contenedor):
        pieza["contenedor"] = contenedor
        if al_crear:
            al_crear()

    if tipo == "imagen":
        cont = ig.crear_imagen({"image_url": url_publica(base, archivos[0]), "caption": pie},
                               alts_de(pieza, 1)[0])
        anotar(cont)
        ig.esperar_listo(cont, 300, 5)
    elif tipo == "carrusel":
        hijos = []
        for i, (rel, alt) in enumerate(zip(archivos, alts_de(pieza, len(archivos))), 1):
            hijo = ig.crear_imagen({"image_url": url_publica(base, rel), "is_carousel_item": "true"}, alt)
            hijos.append(hijo)
            log(f"  placa {i}/{len(archivos)} cargada")
        for hijo in hijos:
            ig.esperar_listo(hijo, 300, 5)
        cont = ig.crear({"media_type": "CAROUSEL", "children": ",".join(hijos), "caption": pie})
        anotar(cont)
        ig.esperar_listo(cont, 300, 5)
    elif tipo == "reel":
        datos = {"media_type": "REELS", "video_url": url_publica(base, archivos[0]),
                 "caption": pie, "share_to_feed": "true"}
        if pieza.get("portada"):
            datos["cover_url"] = url_publica(base, pieza["portada"])
        try:
            cont = ig.crear(datos)
            anotar(cont)
            log("  Instagram está bajando y procesando el video (puede tardar unos minutos)…")
            ig.esperar_listo(cont, 15 * 60, 15)
        except ErrorAPI as e:
            if e.transitorio:
                raise
            # Plan B: subir el archivo directo a Instagram (subida "resumable"), sin que lo baje de GitHub.
            log(f"  Instagram no pudo tomar el video desde GitHub ({e}); lo subo directo.")
            cont = ig.subir_video_directo(datos, archivos[0])
            anotar(cont)
            ig.esperar_listo(cont, 15 * 60, 15)
    elif tipo == "historia":
        # Historia: un contenedor con media_type=STORIES y la imagen (JPEG) o el video. Sin pie, sin alt,
        # sin stickers (la API no los publica). Se espera FINISHED igual que con los reels.
        rel = archivos[0]
        if es_video(rel):
            datos = {"media_type": "STORIES", "video_url": url_publica(base, rel)}
            try:
                cont = ig.crear(datos)
                anotar(cont)
                log("  Instagram está bajando y procesando el video de la historia…")
                ig.esperar_listo(cont, 10 * 60, 10)
            except ErrorAPI as e:
                if e.transitorio:
                    raise
                log(f"  Instagram no pudo tomar el video desde GitHub ({e}); lo subo directo.")
                cont = ig.subir_video_directo(datos, rel)
                anotar(cont)
                ig.esperar_listo(cont, 10 * 60, 10)
        else:
            cont = ig.crear({"media_type": "STORIES", "image_url": url_publica(base, rel)})
            anotar(cont)
            ig.esperar_listo(cont, 300, 5)
    else:
        raise ErrorAPI(f"tipo desconocido: {tipo}")

    # media_publish NO se reintenta a ciegas: antes de reintentar, se mira si ya salió
    # (el contenedor figura PUBLISHED o, en el feed, el pie ya está en la cuenta).
    def ya_salio():
        return ig.contenedor_publicado(cont) or (None if tipo == "historia" else ig.ya_publicada(pieza))

    publicado = ig.llamar("POST", f"{ig.user}/media_publish", {"creation_id": cont},
                          antes_de_reintentar=ya_salio)
    media_id = publicado.get("id")
    permalink = publicado.get("permalink")
    if not permalink and media_id:
        try:
            permalink = ig.llamar("GET", media_id, {"fields": "permalink"}).get("permalink")
        except ErrorAPI:
            permalink = None
    return media_id, permalink


def decidir(pieza, piezas, momento, usados):
    """('publicar', None), ('esperar', motivo) o ('error', motivo). No usa internet."""
    motivo = vencida(pieza, momento)
    if motivo:
        return "error", f"no se publicó: {motivo}"
    dep = pieza.get("depende_de")
    if dep:
        d = buscar(piezas, dep)
        if d is None:
            return "error", f"no se publicó: anuncia '{dep}', que no está en la cola"
        if d.get("estado") == "aprobado":
            return "esperar", f"espera a que salga '{dep}' (el posteo que anuncia)"
        if d.get("estado") != "publicado":
            return "error", f"no se publicó: el posteo que anuncia ('{dep}') está en {d.get('estado')}"
    if usados >= LIMITE_24H:
        return "esperar", (f"ya salieron {usados} publicaciones en 24 h y el tope es {LIMITE_24H}: "
                           "queda para la próxima corrida")
    return "publicar", None


def procesar(piezas, ig, base, momento, ruta=COLA):
    """Publica lo que toca, en orden. Devuelve la cantidad de fallas de esta corrida."""
    fallas = 0
    toca = pendientes_que_tocan(piezas, momento)
    if not toca:
        return 0
    usados = publicadas_en_24h(piezas, momento)
    cupo = ig.cupo()
    if cupo is not None and cupo > usados:
        usados = cupo
    for pieza in toca:
        etiqueta = f"{pieza['id']} ({pieza['tipo']}, {fmt(pieza['fecha_hora'])})"
        log(f"Toca: {etiqueta}")

        accion, motivo = decidir(pieza, piezas, momento, usados)
        if accion == "esperar":
            log(f"  no sale todavía: {motivo}")
            continue
        if accion == "error":
            marcar_error(pieza, motivo, definitivo=True)
            guardar_cola(piezas, ruta)
            fallas += 1
            continue

        from verificar import validar_pieza
        err, _ = validar_pieza(pieza, momento, chequear_hora=False)
        if err:
            marcar_error(pieza, "no pasó la revisión: " + " | ".join(err), definitivo=True)
            guardar_cola(piezas, ruta)
            fallas += 1
            continue

        try:
            ya = ig.contenedor_publicado(pieza.get("contenedor"), estricto=True)
            if ya:
                marcar_publicada(pieza, None, None, "ya había salido en una corrida anterior (el contenedor "
                                 "figura publicado); no se repitió")
                usados += 1
                continue
            if pieza["tipo"] != "historia":  # las historias no tienen pie para comparar
                ya = ig.ya_publicada(pieza)
                if ya:
                    marcar_publicada(pieza, ya["id"], ya.get("permalink"), "ya estaba en la cuenta; no se repitió")
                    continue
            media_id, permalink = publicar_pieza(ig, base, pieza, al_crear=lambda: guardar_cola(piezas, ruta))
            usados += 1
            marcar_publicada(pieza, media_id, permalink, "publicada por el publicador"
                             if media_id else "publicada (Instagram marcó el contenedor como publicado)")
        except ErrorAPI as e:
            pieza["intentos"] = int(pieza.get("intentos") or 0) + 1
            definitivo = (not e.transitorio) or pieza["intentos"] >= MAX_INTENTOS_POR_PIEZA
            marcar_error(pieza, str(e), definitivo=definitivo)
            fallas += 1
        except Exception as e:  # algo inesperado: se frena esta pieza, no se reintenta sola
            marcar_error(pieza, f"falla inesperada: {type(e).__name__}: {e}", definitivo=True)
            fallas += 1
        finally:
            guardar_cola(piezas, ruta)  # se guarda después de cada pieza
    return fallas


def proxima_aprobada(piezas, momento):
    """(hora, id) de lo próximo aprobado con hora futura, o None."""
    futuras = []
    for p in piezas:
        if p.get("estado") != "aprobado":
            continue
        try:
            cuando = leer_fecha(p["fecha_hora"])
        except Exception:
            continue
        if cuando > momento:
            futuras.append((cuando, p["id"]))
    return min(futuras) if futuras else None


def seguir(piezas, ig, base, max_min, candado, ruta=COLA):
    """Después de publicar: si lo próximo aprobado sale dentro de max_min minutos (historias a las
    20:35 y 20:40, por ejemplo), espera y publica. Respeta el límite de la corrida de GitHub (JOB_LIMITE)."""
    fallas = 0
    limite_job = float(os.environ.get("JOB_LIMITE", "0") or 0)
    while True:
        momento = ahora()
        prox = proxima_aprobada(piezas, momento)
        if not prox:
            return fallas
        cuando, id_ = prox
        espera = (cuando - momento).total_seconds()
        if espera > max_min * 60:
            log(f"Lo próximo ({id_}, {fmt(cuando)}) está a más de {max_min} min: termino.")
            return fallas
        if limite_job and time.time() + espera + 900 > limite_job:
            log(f"Lo próximo ({id_}, {fmt(cuando)}) queda fuera del tiempo de esta corrida: lo toma la siguiente.")
            return fallas
        log(f"Lo próximo ({id_}) sale {fmt(cuando)}: espero {max(1, round(espera / 60))} min y sigo.")
        fin = time.time() + espera + 20
        while time.time() < fin:
            time.sleep(min(300, max(0, fin - time.time())))
            candado.refrescar()
        fallas += procesar(piezas, ig, base, ahora(), ruta)


def marcar_publicada(pieza, media_id, permalink, nota):
    pieza["estado"] = "publicado"
    pieza["resultado"] = {"ig_id": media_id, "permalink": permalink,
                          "publicado_en": ahora().isoformat(timespec="seconds"), "nota": nota}
    log(f"  PUBLICADA · id {media_id or 's/d'} · {permalink or ''} · {nota}")
    registrar(f"{pieza['id']} · {pieza['tipo']} · PUBLICADA · {permalink or media_id or 'sin link'} · {nota}")


def marcar_error(pieza, mensaje, definitivo):
    mensaje = limpiar(mensaje)
    if definitivo:
        pieza["estado"] = "error"
        log(f"  ERROR (queda en 'error'; para reintentar: python aprobar.py {pieza['id']}): {mensaje}")
        registrar(f"{pieza['id']} · {pieza['tipo']} · ERROR · {mensaje}")
    else:
        log(f"  falló (intento {pieza.get('intentos')} de {MAX_INTENTOS_POR_PIEZA}; se reintenta en la próxima corrida): {mensaje}")
        registrar(f"{pieza['id']} · {pieza['tipo']} · reintento {pieza.get('intentos')} · {mensaje}")
    pieza["resultado"] = {"error": mensaje, "cuando": ahora().isoformat(timespec="seconds")}


# ---------------------------------------------------------------- modos

def plan_de_corrida(piezas, momento, base=""):
    """Qué haría una corrida real ahora, en orden, sin internet (simula feed, historias, dependencias y tope)."""
    sim = copy.deepcopy(piezas)
    usados = publicadas_en_24h(sim, momento)
    lineas, n = [], 0
    for p in pendientes_que_tocan(sim, momento):
        accion, motivo = decidir(p, sim, momento, usados)
        cab = f"{p['id']} · {p['tipo']} · {fmt(p['fecha_hora'])}"
        if accion == "publicar":
            n += 1
            usados += 1
            p["estado"] = "publicado"
            p["resultado"] = {"publicado_en": momento.isoformat(timespec="seconds")}
            extra = f" · después de '{p['depende_de']}'" if p.get("depende_de") else ""
            lineas.append(f"  {n}. {cab}: {describir(p, base)}{extra}")
        elif accion == "esperar":
            lineas.append(f"  -  {cab}: NO sale todavía ({motivo})")
        else:
            p["estado"] = "error"
            lineas.append(f"  -  {cab}: NO sale y queda en 'error' ({motivo})")
    return lineas, n


def solo_probar(piezas, token, user, base, momento):
    log("MODO SOLO PROBAR: no se publica nada.")
    problemas = 0
    from verificar import validar_pieza

    activas = [p for p in piezas if p.get("estado") in ("borrador", "aprobado")]
    for p in activas:
        err, av = validar_pieza(p, momento)
        log(f"{p['id']} · {p['tipo']} · {p['estado']} · sale {fmt(p['fecha_hora'])}: "
            + ("OK" if not err else f"{len(err)} error(es)"))
        for e in err:
            log(f"    ERROR  {e}")
        problemas += len(err)

    lineas, n = plan_de_corrida(piezas, momento, base)
    log(f"Si fuera una corrida real a las {fmt(momento)}, " + (f"publicaría {n} pieza(s), en este orden:" if n
                                                               else "no publicaría nada.")
        + (f" (van {publicadas_en_24h(piezas, momento)} en 24 h; tope {LIMITE_24H})" if lineas else ""))
    for linea in lineas:
        log(linea)

    if not token or not user:
        log("Sin IG_TOKEN / IG_USER_ID: no probé la cuenta, el cupo ni los archivos en GitHub. "
            "En GitHub van en Settings → Secrets and variables → Actions.")
        if os.environ.get("GITHUB_ACTIONS"):
            problemas += 1
        log("Prueba terminada: " + ("todo en orden (sin la parte de internet)." if not problemas
                                    else f"{problemas} problema(s) para revisar."))
        return 1 if problemas else 0
    ig = Instagram(token, user)
    try:
        yo = ig.llamar("GET", "me", {"fields": "user_id,username,account_type"})
        log(f"Token OK: es la cuenta @{yo.get('username')} ({yo.get('account_type', 'tipo no informado')}).")
        if str(yo.get("user_id")) != str(user) and str(yo.get("id")) != str(user):
            log(f"  OJO: IG_USER_ID no coincide con la cuenta del token. Poné en IG_USER_ID: {yo.get('user_id')}")
            problemas += 1
    except ErrorAPI as e:
        log(f"El token no anda: {e}")
        return 1
    try:
        cupo = ig.llamar("GET", f"{user}/content_publishing_limit", {"fields": "quota_usage,config"})
        datos = (cupo.get("data") or [{}])[0]
        log(f"Permiso para publicar OK. Publicaciones por API en las últimas 24 h: {datos.get('quota_usage', 0)}"
            f" de {datos.get('config', {}).get('quota_total', 100)}.")
    except ErrorAPI as e:
        log(f"No pude leer el cupo de publicación (¿falta el permiso instagram_business_content_publish?): {e}")
        problemas += 1

    if base:
        for p in activas:
            rels = list(p.get("archivos") or []) + ([p["portada"]] if p.get("portada") and p.get("tipo") != "historia" else [])
            try:
                comprobar_urls(ig, base, rels)
                log(f"{p['id']}: los {len(rels)} archivo(s) se pueden bajar desde GitHub.")
            except ErrorAPI as e:
                log(f"{p['id']}: {e}")
                problemas += 1
    else:
        log("Falta MEDIA_BASE_URL: no pude comprobar que Instagram pueda bajar los archivos.")

    log("Prueba terminada: " + ("todo en orden." if not problemas else f"{problemas} problema(s) para revisar."))
    return 1 if problemas else 0


def esperar_proxima(piezas, momento, max_min, simulado=False):
    """GitHub atrasa el cron horas (corre cada 3 a 5 h, no cada 15 min). Si hay algo aprobado que sale
    dentro de max_min minutos, esta corrida espera hasta esa hora y después publica. Si ya hay algo
    vencido, no espera: se publica ahora."""
    if [p for p in pendientes_que_tocan(piezas, momento) if not vencida(p, momento)]:
        log("Hay algo para publicar ya: no espero.")
        return 0
    futuras = []
    for p in piezas:
        if p.get("estado") != "aprobado":
            continue
        try:
            cuando = leer_fecha(p["fecha_hora"])
        except Exception:
            continue
        if cuando > momento:
            futuras.append((cuando, p["id"]))
    if not futuras:
        log("No hay nada aprobado más adelante: no espero.")
        return 0
    cuando, id_ = min(futuras)
    falta = (cuando - momento).total_seconds()
    if falta > max_min * 60:
        log(f"Lo próximo ({id_}, {fmt(cuando)}) está a más de {max_min} min: no espero.")
        return 0
    log(f"Espero {round(falta / 60)} min hasta {fmt(cuando)} para publicar {id_}.")
    if not simulado:
        time.sleep(falta + 20)
    return 0


def main():
    preparar_consola()
    ap = argparse.ArgumentParser(description="Publica en Instagram lo aprobado cuya hora ya pasó.")
    ap.add_argument("--solo-probar", action="store_true", help="no publica nada")
    ap.add_argument("--hay-algo", action="store_true", help="sin internet: ¿hay algo para publicar ahora?")
    ap.add_argument("--esperar", type=int, metavar="MIN",
                    help="si hay algo aprobado en los próximos MIN minutos y nada vencido, espera hasta su hora")
    ap.add_argument("--seguir", type=int, metavar="MIN",
                    help="después de publicar, si lo próximo aprobado sale dentro de MIN minutos, espera y lo publica")
    ap.add_argument("--ahora", help="(solo con --solo-probar, --hay-algo o --esperar) simular otra hora")
    ap.add_argument("--cola", help="(solo con --solo-probar, --hay-algo o --esperar) otra cola.json, para pruebas")
    args = ap.parse_args()
    if args.ahora and not (args.solo_probar or args.hay_algo or args.esperar):
        ap.error("--ahora solo se puede usar con --solo-probar, --hay-algo o --esperar")
    if args.cola and not (args.solo_probar or args.hay_algo or args.esperar):
        ap.error("--cola solo se puede usar con --solo-probar, --hay-algo o --esperar (las publicaciones reales usan cola.json)")
    ruta = Path(args.cola) if args.cola else COLA

    momento = leer_fecha(args.ahora) if args.ahora else ahora()
    token = os.environ.get("IG_TOKEN", "").strip()
    user = os.environ.get("IG_USER_ID", "").strip()
    base = os.environ.get("MEDIA_BASE_URL", "").strip()

    if args.esperar:
        return esperar_proxima(cargar_cola(ruta), momento, args.esperar, simulado=bool(args.ahora))

    if args.hay_algo:
        toca = pendientes_que_tocan(cargar_cola(ruta), momento)
        print("si" if toca else "no")
        salida = os.environ.get("GITHUB_OUTPUT")
        if salida:
            with open(salida, "a", encoding="utf-8") as f:
                f.write(f"toca={'si' if toca else 'no'}\n")
        return 0

    with Candado() as candado:
        piezas = cargar_cola(ruta)
        if args.solo_probar:
            return solo_probar(piezas, token, user, base, momento)

        toca = pendientes_que_tocan(piezas, momento)
        if not toca:
            log(f"Nada para publicar ahora ({fmt(momento)}).")
            return 0
        faltan = [n for n, v in (("IG_TOKEN", token), ("IG_USER_ID", user), ("MEDIA_BASE_URL", base)) if not v]
        if faltan:
            log("No puedo publicar: faltan " + ", ".join(faltan) + ". Nada cambió en cola.json.")
            return 1
        ig = Instagram(token, user)
        fallas = procesar(piezas, ig, base, momento)
        guardar_cola(piezas, COLA)
        if args.seguir:
            fallas += seguir(piezas, ig, base, args.seguir, candado)
            guardar_cola(piezas, COLA)
        log("Corrida terminada: " + ("sin problemas." if not fallas else f"{fallas} pieza(s) con problemas (ver arriba)."))
        return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
