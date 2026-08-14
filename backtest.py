"""Validacion historica del detector.

Corre EXACTAMENTE el mismo camino que produccion: multi-modelo con consenso
(`_combinar_multimodelo` + `evaluar_dia_multimodelo` + `detectar_ventanas`).
Un backtest que probara el camino single-modelo no validaria nada, porque el
gate que corre en vivo exige que la condicion pase en varios modelos y ese
requisito es el que decide la mayor parte de los dias.

Criterios objetivos:
  - Volumen: entre 10 y 25 ventanas por spot por anio. Menos de 5 es un filtro
    estrangulado (el usuario se pierde swells); mas de 60 es ruido.
  - Estacionalidad: la distribucion mensual tiene que coincidir con la
    temporada declarada del spot.

SESGO CONOCIDO DEL BACKTEST
---------------------------
Produccion consulta tres modelos de olas (gwam, meteofrance_wave,
ncep_gfswave025) y exige que el gate pase en al menos MINIMO_MODELOS_DE_ACUERDO
= 2. El archivo de Open-Meteo no sirve los tres en todo el periodo:

  2023-01-01 .. 2024-06-07   gwam + meteofrance_wave
  2024-06-08 .. 2024-06-18   solo meteofrance_wave
  2024-06-19 .. 2025-12-08   meteofrance_wave + ncep_gfswave025
  2025-12-09 en adelante     los tres

Con dos fuentes, "2 de 3" se vuelve "2 de 2": son TODAS, o sea mas estricto
que produccion. El backtest subestima el volumen. La magnitud se mide con
`--modelos-olas` sobre un periodo donde los tres coexisten (ver
docs/resultados-backtest.md); no se compensa con ningun truco en el codigo.

Ademas ncep_gfswave025 tiene 5 de los 13 spots en una celda enmascarada como
tierra y devuelve 0.0, que `surf.fetch` descarta como dato faltante. En esos
spots el tramo 2024-06-19..2025-12-08 queda con UNA sola fuente, que es mas
permisivo. `analizar` reporta `fuentes_promedio` para que el sesgo sea
visible spot por spot en vez de quedar escondido en el promedio.
"""
import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import requests

from surf.alert import detectar_ventanas
from surf.consenso import MODELOS_OLAS, MODELOS_VIENTO, evaluar_dia_multimodelo
from surf.fetch import _CAMPOS_CLIMA, _CAMPOS_MARINE, ErrorDatos, _combinar_multimodelo
from surf.spots import Spot, cargar_spots

URL_MARINE_ARCHIVO = "https://marine-api.open-meteo.com/v1/marine"
URL_CLIMA_ARCHIVO = "https://archive-api.open-meteo.com/v1/archive"

RUTA_SPOTS = Path(__file__).resolve().parent / "spots.yaml"
CACHE_DIR = Path(__file__).resolve().parent / ".cache_backtest"

TIMEOUT_S = 180

RANGO_SANO = (10, 25)
# Debajo de LIMITE_ESTRANGULADO el usuario se pierde swells reales; encima de
# LIMITE_RUIDO va a terminar ignorando el bot. Entre esos limites y RANGO_SANO
# hay una zona "bajo"/"alto": apretado o suelto, pero no roto.
LIMITE_ESTRANGULADO = 5
LIMITE_RUIDO = 60

# Fraccion minima de ventanas que tiene que caer dentro de la temporada
# declarada para considerar que la orientacion de la ventana de swell es
# correcta.
FRACCION_EN_TEMPORADA = 0.6

DIAS_POR_ANIO = 365.25


# --- obtencion de datos -----------------------------------------------------

def _clave(url: str, params: dict) -> str:
    crudo = url + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.sha1(crudo.encode("utf-8")).hexdigest()


def _pedir_cacheado(url: str, params: dict, sesion, cache_dir: Path) -> dict:
    """GET contra el archivo, con cache en disco.

    Sin cache, cada iteracion de calibracion vuelve a bajar 3 anios de datos
    horarios por 13 spots. El directorio esta gitignoreado.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    destino = cache_dir / f"{_clave(url, params)}.json.gz"
    if destino.exists():
        with gzip.open(destino, "rt", encoding="utf-8") as fh:
            return json.load(fh)

    cliente = sesion or requests
    r = cliente.get(url, params=params, timeout=TIMEOUT_S)
    r.raise_for_status()
    datos = r.json()
    if datos.get("error"):
        raise ErrorDatos(f"archivo: {datos.get('reason')}")

    # Se escribe a un temporal y se renombra: si el proceso muere a mitad de
    # la escritura, la proxima corrida no lee un .gz truncado como si fuera
    # una respuesta valida.
    temporal = destino.with_suffix(".tmp")
    with gzip.open(temporal, "wt", encoding="utf-8") as fh:
        json.dump(datos, fh)
    temporal.replace(destino)
    return datos


def _tramos(desde: date, hasta: date) -> list:
    """Parte el rango en anios calendario.

    Un unico request de 3 anios con 3 modelos devuelve un JSON grande y un
    timeout pierde todo; por anio, la cache retiene lo que ya bajo. Los cortes
    caen entre dias, asi que ningun dia queda partido en dos tramos.
    """
    tramos = []
    inicio = desde
    while inicio <= hasta:
        fin_anio = date(inicio.year, 12, 31)
        fin = min(fin_anio, hasta)
        tramos.append((inicio, fin))
        inicio = fin + timedelta(days=1)
    return tramos


def obtener_historico(spot: Spot, desde: date, hasta: date, *, sesion=None,
                      cache_dir: Path = CACHE_DIR, modelos_olas: list = None,
                      modelos_viento: list = None) -> dict:
    """Trae datos de archivo y los combina igual que produccion.

    Devuelve `dict[date, list[HoraMultiModelo]]`, el mismo tipo que consume
    `evaluar_dia_multimodelo` en vivo.
    """
    olas = list(modelos_olas or MODELOS_OLAS)
    viento = list(modelos_viento or MODELOS_VIENTO)

    por_dia: dict = {}
    for ini, fin in _tramos(desde, hasta):
        base = {"latitude": spot.lat, "longitude": spot.lon, "timezone": "auto",
                "start_date": ini.isoformat(), "end_date": fin.isoformat()}

        marine = _pedir_cacheado(
            URL_MARINE_ARCHIVO,
            {**base, "hourly": ",".join(_CAMPOS_MARINE), "models": ",".join(olas)},
            sesion, cache_dir)
        clima = _pedir_cacheado(
            URL_CLIMA_ARCHIVO,
            {**base, "hourly": ",".join(_CAMPOS_CLIMA), "models": ",".join(viento),
             "daily": "sunrise,sunset", "wind_speed_unit": "kmh"},
            sesion, cache_dir)

        por_dia.update(_combinar_multimodelo(marine, clima, olas, viento))

    return por_dia


# --- analisis ---------------------------------------------------------------

def _anios_cubiertos(por_dia: dict) -> float:
    """Duracion real del periodo, en anios.

    Se normaliza por dias cubiertos y no por anios calendario distintos: un
    tramo de seis meses tiene un solo anio calendario, y dividir por 1 daria
    la mitad de la tasa real. Importa porque los tramos por regimen de fuentes
    no caen en limites de anio.
    """
    if not por_dia:
        return 1.0
    fechas = sorted(por_dia)
    dias = (fechas[-1] - fechas[0]).days + 1
    return max(dias / DIAS_POR_ANIO, 1.0 / DIAS_POR_ANIO)


def _detalle_dia(d) -> dict:
    r = d.resumen or {}
    return {
        "fecha": d.fecha.isoformat(),
        "score": round(d.score, 1),
        "altura": round(r.get("altura", 0.0), 2),
        "periodo": round(r.get("periodo", 0.0), 1),
        "direccion": round(r.get("direccion", 0.0)),
        "viento_kmh": round(r.get("viento_kmh", 0.0), 1),
        "viento_direccion": round(r.get("viento_direccion", 0.0)),
        "horas_buenas": d.horas_buenas,
        "concordancia": d.concordancia,
        "modelos": list(d.modelos),
    }


def analizar(spot: Spot, por_dia: dict) -> dict:
    """Corre el detector multi-modelo sobre el historico y resume el resultado."""
    dias = [evaluar_dia_multimodelo(horas, spot, fecha)
            for fecha, horas in sorted(por_dia.items())]
    ventanas = detectar_ventanas(dias)
    buenos = [d for d in dias if d.es_bueno]

    anios = _anios_cubiertos(por_dia)
    por_mes = Counter(v.desde.month for v in ventanas)
    dias_por_mes = Counter(d.fecha.month for d in buenos)

    conteos = [len(h.por_modelo) for horas in por_dia.values() for h in horas]
    fuentes = sum(conteos) / len(conteos) if conteos else 0.0

    return {
        "spot_id": spot.id,
        "desde": min(por_dia).isoformat() if por_dia else None,
        "hasta": max(por_dia).isoformat() if por_dia else None,
        "dias_analizados": len(dias),
        "total_ventanas": len(ventanas),
        "ventanas_por_anio": len(ventanas) / anios,
        "dias_buenos": len(buenos),
        "dias_buenos_por_anio": len(buenos) / anios,
        "por_mes": dict(por_mes),
        "dias_por_mes": dict(dias_por_mes),
        "fuentes_promedio": round(fuentes, 2),
        "top_dias": [_detalle_dia(d) for d in sorted(buenos, key=lambda d: -d.score)[:10]],
        "temporada_declarada": list(spot.temporada),
    }


def veredicto(resultado: dict) -> str:
    """Clasifica el volumen de alertas."""
    v = resultado["ventanas_por_anio"]
    if v < LIMITE_ESTRANGULADO:
        return "estrangulado"
    if v < RANGO_SANO[0]:
        return "bajo"
    if v <= RANGO_SANO[1]:
        return "sano"
    if v <= LIMITE_RUIDO:
        return "alto"
    return "ruido"


def coincide_la_temporada(resultado: dict) -> bool:
    """Verifica que la mayoria de las ventanas caigan en la temporada declarada."""
    por_mes = resultado["por_mes"]
    total = sum(por_mes.values())
    if total == 0:
        return False
    en_temporada = sum(n for m, n in por_mes.items()
                       if m in resultado["temporada_declarada"])
    return en_temporada / total >= FRACCION_EN_TEMPORADA


def concentracion(resultado: dict) -> float:
    """Cuanto se concentran las ventanas en temporada por encima del azar.

    `coincide_la_temporada` compara contra un 60% fijo, pero una temporada de
    7 meses ya cubre el 58% del anio: una distribucion uniforme rozaria el
    umbral sin decir nada. Este cociente (fraccion observada / fraccion
    esperada por azar) vale 1.0 si las ventanas se reparten uniforme y ~1.7 si
    caen todas en temporada. Es la medida que hay que leer para juzgar si la
    hipotesis de temporada se sostiene.
    """
    por_mes = resultado["por_mes"]
    total = sum(por_mes.values())
    meses = resultado["temporada_declarada"]
    if total == 0 or not meses:
        return 0.0
    observada = sum(n for m, n in por_mes.items() if m in meses) / total
    return observada / (len(meses) / 12)


# --- CLI --------------------------------------------------------------------

def _linea_meses(por_mes: dict) -> str:
    return " ".join(f"{m:02d}:{por_mes.get(m, 0)}" for m in range(1, 13))


def correr(spots: list, desde: date, hasta: date, modelos_olas=None,
           cache_dir: Path = CACHE_DIR) -> tuple:
    """Corre el backtest y devuelve (resultados, problemas)."""
    resultados = []
    problemas = 0

    for spot in spots:
        try:
            por_dia = obtener_historico(spot, desde, hasta, cache_dir=cache_dir,
                                        modelos_olas=modelos_olas)
            r = analizar(spot, por_dia)
        except Exception as e:  # noqa: BLE001
            print(f"{spot.id:20} ERROR: {e}", file=sys.stderr)
            problemas += 1
            continue

        v = veredicto(r)
        r["veredicto_volumen"] = v
        r["temporada_ok"] = coincide_la_temporada(r)
        r["concentracion"] = round(concentracion(r), 2)
        resultados.append(r)

        temp = "ok" if r["temporada_ok"] else "NO COINCIDE"
        malo = v in ("estrangulado", "ruido") or not r["temporada_ok"]
        if malo:
            problemas += 1
        print(f"{'!!' if malo else '  '} {spot.id:20} {r['ventanas_por_anio']:5.1f}/anio  "
              f"volumen={v:12} temporada={temp:11} conc={r['concentracion']:.2f}  "
              f"fuentes={r['fuentes_promedio']:.2f}")
        print(f"     ventanas/mes: {_linea_meses(r['por_mes'])}")
        print(f"     dias/mes:     {_linea_meses(r['dias_por_mes'])}")

    return resultados, problemas


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Backtest historico del detector.")
    p.add_argument("--desde", default="2023-01-01")
    p.add_argument("--hasta", default="2025-12-31")
    p.add_argument("--spots", default="", help="ids separados por coma")
    p.add_argument("--modelos-olas", default="",
                   help="modelos de olas a usar (por defecto los de produccion)")
    p.add_argument("--json", default="", help="volcar los resultados a este archivo")
    args = p.parse_args(argv)

    spots = cargar_spots(RUTA_SPOTS)
    if args.spots:
        pedidos = [s.strip() for s in args.spots.split(",")]
        spots = [s for s in spots if s.id in pedidos]

    modelos = [m.strip() for m in args.modelos_olas.split(",")] if args.modelos_olas else None

    resultados, problemas = correr(spots, date.fromisoformat(args.desde),
                                   date.fromisoformat(args.hasta), modelos)

    if args.json:
        Path(args.json).write_text(json.dumps(resultados, indent=2, ensure_ascii=False))

    print(f"\n{problemas} spots requieren ajuste.")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
