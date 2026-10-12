"""Publica en Instagram lo aprobado cuya hora ya pasó (API oficial, graph.instagram.com).

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
"""

import argparse
import os
import sys
import time
from urllib.parse import quote

from comun import (COLA, Candado, ahora, cargar_cola, fmt, guardar_cola, leer_fecha, limpiar,
                   log, normalizar, pendientes_que_tocan, preparar_consola, registrar, vencida)

VERSION = os.environ.get("IG_API_VERSION", "v23.0").strip() or "v23.0"
API = f"https://graph.instagram.com/{VERSION}"
MAX_INTENTOS_POR_PIEZA = 3          # corridas que se reintenta antes de quedar en "error"
ESPERA_REINTENTO = (5, 20, 60)      # segundos entre reintentos dentro de una misma llamada
CODIGOS_TRANSITORIOS = {1, 2, 4, 17, 32, 341, 368, 613, -1, -2}


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


def publicar_pieza(ig, base, pieza):
    tipo, pie, archivos = pieza["tipo"], pieza["pie"], pieza["archivos"]
    comprobar_urls(ig, base, archivos + ([pieza["portada"]] if pieza.get("portada") else []))

    if tipo == "imagen":
        cont = ig.crear_imagen({"image_url": url_publica(base, archivos[0]), "caption": pie},
                               alts_de(pieza, 1)[0])
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
        ig.esperar_listo(cont, 300, 5)
    elif tipo == "reel":
        datos = {"media_type": "REELS", "video_url": url_publica(base, archivos[0]),
                 "caption": pie, "share_to_feed": "true"}
        if pieza.get("portada"):
            datos["cover_url"] = url_publica(base, pieza["portada"])
        try:
            cont = ig.crear(datos)
            log("  Instagram está bajando y procesando el video (puede tardar unos minutos)…")
            ig.esperar_listo(cont, 15 * 60, 15)
        except ErrorAPI as e:
            if e.transitorio:
                raise
            # Plan B: subir el archivo directo a Instagram (subida "resumable"), sin que lo baje de GitHub.
            log(f"  Instagram no pudo tomar el video desde GitHub ({e}); lo subo directo.")
            cont = ig.subir_video_directo(datos, archivos[0])
            ig.esperar_listo(cont, 15 * 60, 15)
    else:
        raise ErrorAPI(f"tipo desconocido: {tipo}")

    # media_publish NO se reintenta a ciegas: antes de reintentar, se mira si ya salió.
    publicado = ig.llamar("POST", f"{ig.user}/media_publish", {"creation_id": cont},
                          antes_de_reintentar=lambda: ig.ya_publicada(pieza))
    media_id = publicado["id"]
    permalink = publicado.get("permalink")
    if not permalink:
        try:
            permalink = ig.llamar("GET", media_id, {"fields": "permalink"}).get("permalink")
        except ErrorAPI:
            permalink = None
    return media_id, permalink


def procesar(piezas, ig, base, momento):
    """Publica lo que toca. Devuelve la cantidad de fallas de esta corrida."""
    fallas = 0
    for pieza in pendientes_que_tocan(piezas, momento):
        etiqueta = f"{pieza['id']} ({pieza['tipo']}, {fmt(pieza['fecha_hora'])})"
        log(f"Toca: {etiqueta}")

        motivo = vencida(pieza, momento)
        if motivo:
            marcar_error(pieza, f"no se publicó: {motivo}", definitivo=True)
            guardar_cola(piezas)
            fallas += 1
            continue

        from verificar import validar_pieza
        err, _ = validar_pieza(pieza, momento, chequear_hora=False)
        if err:
            marcar_error(pieza, "no pasó la revisión: " + " | ".join(err), definitivo=True)
            guardar_cola(piezas)
            fallas += 1
            continue

        try:
            ya = ig.ya_publicada(pieza)
            if ya:
                marcar_publicada(pieza, ya["id"], ya.get("permalink"), "ya estaba en la cuenta; no se repitió")
                continue
            media_id, permalink = publicar_pieza(ig, base, pieza)
            marcar_publicada(pieza, media_id, permalink, "publicada por el publicador")
        except ErrorAPI as e:
            pieza["intentos"] = int(pieza.get("intentos") or 0) + 1
            definitivo = (not e.transitorio) or pieza["intentos"] >= MAX_INTENTOS_POR_PIEZA
            marcar_error(pieza, str(e), definitivo=definitivo)
            fallas += 1
        except Exception as e:  # algo inesperado: se frena esta pieza, no se reintenta sola
            marcar_error(pieza, f"falla inesperada: {type(e).__name__}: {e}", definitivo=True)
            fallas += 1
        finally:
            guardar_cola(piezas)  # se guarda después de cada pieza
    return fallas


def marcar_publicada(pieza, media_id, permalink, nota):
    pieza["estado"] = "publicado"
    pieza["resultado"] = {"ig_id": media_id, "permalink": permalink,
                          "publicado_en": ahora().isoformat(timespec="seconds"), "nota": nota}
    log(f"  PUBLICADA · id {media_id} · {permalink or ''} · {nota}")
    registrar(f"{pieza['id']} · {pieza['tipo']} · PUBLICADA · {permalink or media_id} · {nota}")


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

    if not token or not user:
        log("Faltan los secretos IG_TOKEN y/o IG_USER_ID: cargalos en GitHub (Settings → Secrets and variables → Actions).")
        return 1
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
            rels = list(p.get("archivos") or []) + ([p["portada"]] if p.get("portada") else [])
            try:
                comprobar_urls(ig, base, rels)
                log(f"{p['id']}: los {len(rels)} archivo(s) se pueden bajar desde GitHub.")
            except ErrorAPI as e:
                log(f"{p['id']}: {e}")
                problemas += 1
    else:
        log("Falta MEDIA_BASE_URL: no pude comprobar que Instagram pueda bajar los archivos.")

    toca = pendientes_que_tocan(piezas, momento)
    log("Si fuera una corrida real, publicaría ahora: " + (", ".join(p["id"] for p in toca) if toca else "nada"))
    log("Prueba terminada: " + ("todo en orden." if not problemas else f"{problemas} problema(s) para revisar."))
    return 1 if problemas else 0


def main():
    preparar_consola()
    ap = argparse.ArgumentParser(description="Publica en Instagram lo aprobado cuya hora ya pasó.")
    ap.add_argument("--solo-probar", action="store_true", help="no publica nada")
    ap.add_argument("--hay-algo", action="store_true", help="sin internet: ¿hay algo para publicar ahora?")
    ap.add_argument("--ahora", help="(solo con --solo-probar o --hay-algo) simular otra hora")
    args = ap.parse_args()
    if args.ahora and not (args.solo_probar or args.hay_algo):
        ap.error("--ahora solo se puede usar con --solo-probar o --hay-algo")

    momento = leer_fecha(args.ahora) if args.ahora else ahora()
    token = os.environ.get("IG_TOKEN", "").strip()
    user = os.environ.get("IG_USER_ID", "").strip()
    base = os.environ.get("MEDIA_BASE_URL", "").strip()

    if args.hay_algo:
        toca = pendientes_que_tocan(cargar_cola(), momento)
        print("si" if toca else "no")
        salida = os.environ.get("GITHUB_OUTPUT")
        if salida:
            with open(salida, "a", encoding="utf-8") as f:
                f.write(f"toca={'si' if toca else 'no'}\n")
        return 0

    with Candado():
        piezas = cargar_cola()
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
        fallas = procesar(piezas, Instagram(token, user), base, momento)
        guardar_cola(piezas, COLA)
        log("Corrida terminada: " + ("sin problemas." if not fallas else f"{fallas} pieza(s) con problemas (ver arriba)."))
        return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
