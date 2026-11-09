#!/usr/bin/env python3
"""
scripts/verificar_auditoria.py — Verificador de integridad de la auditoría.

Recorre la cadena de `evento_auditoria`, recalcula cada hash y señala el
primer evento alterado, borrado o reordenado. Se puede ejecutar desde el host
o dentro del contenedor:

    python3 scripts/verificar_auditoria.py
    docker compose exec app python scripts/verificar_auditoria.py

Código de salida: 0 si la cadena está íntegra, 1 si detectó una alteración,
2 si no pudo consultar la base. Así sirve en un pipeline de CI.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comun import auditoria  # noqa: E402


def main() -> int:
    try:
        resultado = auditoria.verificar_cadena()
    except Exception as exc:  # noqa: BLE001
        print(f"No se pudo consultar la auditoría: {exc}")
        print("¿Está levantado pg_central? Pruebe: docker compose ps")
        return 2

    print("=" * 72)
    print("VERIFICACIÓN DE LA CADENA DE AUDITORÍA")
    print("=" * 72)
    print(f"Eventos revisados: {resultado['total_eventos']}")

    if resultado["integra"]:
        print("Resultado: CADENA ÍNTEGRA")
        print(f"Hash de cabeza: {resultado['hash_cabeza']}")
        print("\nCada evento encadena con el hash del anterior:")
        print("    hash = SHA-256(hash_anterior + contenido_canónico)")
        return 0

    print("Resultado: CADENA ALTERADA")
    print(f"Primer evento afectado: #{resultado['evento_alterado']}")
    print(f"Motivo: {resultado['motivo']}")
    print(f"Hash esperado:   {resultado['hash_esperado']}")
    print(f"Hash encontrado: {resultado['hash_encontrado']}")
    evento = resultado.get("evento") or {}
    if evento:
        print("\nEvento señalado:")
        for clave, valor in evento.items():
            print(f"    {clave:12} {valor}")
    print("\nTodo lo posterior a ese evento queda bajo sospecha: el hash de cada")
    print("eslabón depende del anterior.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
