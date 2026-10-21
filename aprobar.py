"""Pasa piezas de "borrador" (o "error") a "aprobado". Solo lo aprobado se publica.

Uso:
  python aprobar.py 2026-10-14             las piezas de ese día, feed e historias (o la que tenga ese id,
                                           ej. 2026-10-21_h2 para una historia sola)
  python aprobar.py semana                 las de esta semana, de hoy al domingo
  python aprobar.py semana 2026-10-19      las de la semana de ese día (lunes a domingo)
  python aprobar.py todo                   todos los borradores con hora futura
  python aprobar.py --volver 2026-10-14    la pasa a borrador (para frenarla)
  python aprobar.py --ver                  lista la cola

Antes de aprobar, cada pieza pasa por la misma revisión que verificar.py:
si tiene errores, no se aprueba.
Después: Commit y Push en GitHub Desktop. Si no, GitHub no se entera.
"""

import argparse
import sys
from datetime import timedelta

from comun import (ahora, buscar, cargar_cola, clave_orden, fmt, guardar_cola, leer_fecha, ordenar,
                   preparar_consola)


def elegir(piezas, que, fecha_semana, momento):
    if que == "todo":
        return [p for p in piezas if leer_fecha(p["fecha_hora"]) > momento]
    if que == "semana":
        base = leer_fecha(fecha_semana + "T12:00") if fecha_semana else momento
        lunes = (base - timedelta(days=base.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        desde = max(lunes, momento) if not fecha_semana else lunes
        hasta = lunes + timedelta(days=7)
        return [p for p in piezas if desde <= leer_fecha(p["fecha_hora"]) < hasta]
    return [p for p in piezas
            if str(p.get("id")) == que or leer_fecha(p["fecha_hora"]).date().isoformat() == que]


def main():
    preparar_consola()
    ap = argparse.ArgumentParser(description="Aprueba piezas de cola.json.")
    ap.add_argument("que", nargs="?", help="fecha (2026-10-14), id, 'semana' o 'todo'")
    ap.add_argument("fecha_semana", nargs="?", help="con 'semana': un día de esa semana")
    ap.add_argument("--volver", action="store_true", help="pasar a borrador en vez de aprobar")
    ap.add_argument("--ver", action="store_true", help="solo listar")
    ap.add_argument("--cola", help="otra cola.json (para pruebas)")
    args = ap.parse_args()

    cola = [args.cola] if args.cola else []
    piezas = cargar_cola(*cola)
    momento = ahora()

    if args.ver or not args.que:
        for p in sorted(piezas, key=clave_orden):
            print(f"{fmt(p['fecha_hora']):<16} {p['id']:<22} {p['tipo']:<9} {p['estado']}")
        if not args.que:
            print("\nUso: python aprobar.py 2026-10-14 | semana | todo   (o --volver 2026-10-14)")
        return 0

    elegidas = elegir(piezas, args.que.lower(), args.fecha_semana, momento)
    if not elegidas:
        print(f"No hay piezas para '{args.que}'. Mirá la lista con: python aprobar.py --ver")
        return 1

    from verificar import validar_pieza

    cambios, rechazadas = 0, 0
    for p in sorted(elegidas, key=clave_orden):
        etiqueta = f"{p['id']} ({p['tipo']}, {fmt(p['fecha_hora'])})"
        if args.volver:
            if p["estado"] == "aprobado":
                p["estado"] = "borrador"
                cambios += 1
                print(f"  {etiqueta}: vuelve a borrador. No se publica hasta que la apruebes otra vez.")
            else:
                print(f"  {etiqueta}: está en {p['estado']}, no la toco.")
            continue
        if p["estado"] == "publicado":
            print(f"  {etiqueta}: ya está publicada.")
            continue
        if p["estado"] == "aprobado":
            print(f"  {etiqueta}: ya estaba aprobada.")
            continue
        p_prueba = dict(p, estado="aprobado")
        err, av = validar_pieza(p_prueba, momento)
        if err:
            rechazadas += 1
            print(f"  {etiqueta}: NO se aprueba:")
            for e in err:
                print(f"      ERROR  {e}")
            continue
        p["estado"] = "aprobado"
        p["intentos"] = 0
        if p.get("resultado") and p["resultado"].get("error"):
            p["resultado"] = None
        cambios += 1
        print(f"  {etiqueta}: APROBADA. Sale {fmt(p['fecha_hora'])}.")
        for a in av:
            print(f"      aviso  {a}")
        dep = p.get("depende_de")
        if dep:
            d = buscar(piezas, dep)
            if d is None or d.get("estado") not in ("aprobado", "publicado"):
                print(f"      aviso  anuncia '{dep}', que {'no está en la cola' if d is None else 'está en ' + str(d.get('estado'))}: "
                      "esta historia sale solo cuando salga ese posteo")

    if cambios:
        ordenar(piezas)
        guardar_cola(piezas, *cola)
        print(f"\n{cambios} cambio(s) guardado(s) en cola.json.")
        print("Ahora: GitHub Desktop → Commit → Push origin. Si no hacés Push, GitHub no se entera.")
    return 1 if rechazadas else 0


if __name__ == "__main__":
    sys.exit(main())
