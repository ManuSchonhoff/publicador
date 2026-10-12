"""Renueva el token largo de Instagram (vale 60 días; renovarlo lo extiende otros 60).

Lo corre GitHub el día 1 de cada mes. Nunca imprime el token.

  python renovar_token.py --salida ARCHIVO
      Si el token nuevo es distinto del actual, lo escribe en ARCHIVO (para que el
      workflow lo guarde en los secretos) y deja cambio=si en GITHUB_OUTPUT.
"""

import argparse
import os
import sys

from comun import limpiar, log, preparar_consola


def main():
    preparar_consola()
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()

    import requests

    token = os.environ.get("IG_TOKEN", "").strip()
    if not token:
        log("Falta el secreto IG_TOKEN.")
        return 1
    try:
        r = requests.get("https://graph.instagram.com/refresh_access_token",
                         params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=60)
        cuerpo = r.json()
    except Exception as e:
        log(f"No pude hablar con Instagram: {limpiar(type(e).__name__)}")
        return 1
    if not r.ok or "access_token" not in cuerpo:
        err = cuerpo.get("error", {}) if isinstance(cuerpo, dict) else {}
        log(f"Instagram no renovó el token: {limpiar(err.get('message') or r.text[:300])}")
        log("Si dice que el token venció o es inválido: generá uno nuevo (GUIA.md, paso 6) y pegalo en el secreto IG_TOKEN.")
        return 1

    nuevo = cuerpo["access_token"].strip()
    dias = int(cuerpo.get("expires_in", 0)) // 86400
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{nuevo}", flush=True)  # GitHub lo tapa en cualquier registro
    cambio = nuevo != token
    if cambio:
        with open(args.salida, "w", encoding="utf-8") as f:
            f.write(nuevo)
    salida = os.environ.get("GITHUB_OUTPUT")
    if salida:
        with open(salida, "a", encoding="utf-8") as f:
            f.write(f"cambio={'si' if cambio else 'no'}\n")
    log(f"Token renovado: vale {dias} días más." + (" Instagram dio un token nuevo: hay que guardarlo en el secreto." if cambio else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
