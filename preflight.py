#!/usr/bin/env python3
"""Comprueba que los puertos que compose va a publicar estan libres.

Se comprueba CONECTANDO, no haciendo bind: con SO_REUSEADDR un bind puede
tener exito sobre un puerto que ya esta escuchando, y entonces el chequeo
miente. Esta maquina tiene mucho contenedor de otros proyectos levantado,
asi que el choque es el caso normal, no el raro.
"""
import socket
import subprocess
import sys

# solo el frontend se publica; backend, mariadb y qdrant son internos
PUBLICADOS = {"frontend": 8090}


def escuchando(port, host="127.0.0.1"):
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def quien(port):
    for cmd in (["ss", "-tlnp"], ["netstat", "-tlnp"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True).stdout
        except FileNotFoundError:
            continue
        for l in out.splitlines():
            if f":{port} " in l or l.split()[3:4] and l.split()[3].endswith(f":{port}"):
                return l.strip()[:110]
    return "(proceso desconocido)"


def main():
    malos = []
    for nombre, port in PUBLICADOS.items():
        if escuchando(port):
            malos.append((nombre, port))
            print(f"  OCUPADO  {port}  ({nombre})\n           {quien(port)}")
        else:
            print(f"  libre    {port}  ({nombre})")

    if malos:
        print("\nCambia el puerto en compose.yaml y en PUBLICADOS, o para lo que "
              "lo ocupa.\nEn este proyecto se publica solo el frontend: mariadb, "
              "qdrant y el backend\nno exponen puertos al host y no pueden chocar.")
        return 1
    print("\nPuertos libres. `docker compose up -d --build`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
