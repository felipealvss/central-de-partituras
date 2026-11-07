"""Programas externos (homr, Audiveris, MuseScore) com limite de tempo, e encerramento de grupos de processos.

O servidor roda cada conversão num processo próprio, em sessão nova (grupo próprio). Os motores são filhos
desse processo e herdam o grupo; cancelar = encerrar o grupo inteiro (inclusive o Java do Audiveris).
"""
import os
import signal
import subprocess
import time
from pathlib import Path

from .erros import ErroConversao


def rodar(cmd, *, timeout, log=None, env=None, cwd=None, nome=None):
    """Roda um programa e espera. Passou do limite: interrompe e gera ErroConversao. Devolve o código de saída."""
    nome = nome or Path(str(cmd[0])).name
    saida = open(log, 'w', encoding='utf-8', errors='replace') if log else subprocess.DEVNULL
    try:
        p = subprocess.Popen([str(c) for c in cmd], stdout=saida, stderr=subprocess.STDOUT, env=env, cwd=cwd)
        try:
            return p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            parar(p)
            raise ErroConversao(f'{nome} passou do limite de {max(timeout // 60, 1)} min e foi interrompido.')
        except BaseException:
            parar(p)
            raise
    finally:
        if log:
            saida.close()


def parar(p, espera=5):
    """Pede para o processo terminar; se não terminar a tempo, mata."""
    if p.poll() is not None:
        return
    p.terminate()
    try:
        p.wait(espera)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()


def _grupo_vivo(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def encerrar_grupo(p, espera=5.0):
    """SIGTERM para o grupo de processos de `p` (criado com start_new_session=True); SIGKILL no que sobrar."""
    pgid = p.pid
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        p.poll()
        return
    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        p.poll()  # recolhe o processo principal, se já saiu
        if not _grupo_vivo(pgid):
            break
        time.sleep(0.1)
    if _grupo_vivo(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        p.wait(espera)
    except subprocess.TimeoutExpired:
        pass
