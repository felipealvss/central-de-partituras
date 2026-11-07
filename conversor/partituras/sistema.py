"""Integração com a área de trabalho (GNOME): escolher pasta, abrir no MuseScore, mostrar na pasta, avisos."""
import shutil
import subprocess
import threading
from pathlib import Path

_dialogo = threading.Lock()


class Ocupado(Exception):
    """Já existe uma janela de escolha aberta."""


def _soltar(cmd):
    """Abre um programa independente do servidor (não espera, não herda a saída)."""
    subprocess.Popen([str(c) for c in cmd], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def escolher_pasta(inicial=None, titulo='Escolha a pasta de saída'):
    """Janela nativa de escolha de pasta (zenity). Devolve o caminho ou None se cancelada."""
    if not shutil.which('zenity'):
        raise RuntimeError('zenity não está instalado.')
    if not _dialogo.acquire(blocking=False):
        raise Ocupado('Já existe uma janela de escolha aberta (veja se ela está atrás da Central).')
    try:
        cmd = ['zenity', '--file-selection', '--directory', f'--title={titulo}']
        if inicial and Path(inicial).is_dir():
            cmd.append(f'--filename={Path(inicial)}/')
        r = subprocess.run(cmd, capture_output=True, text=True)
        caminho = r.stdout.strip()
        return caminho if r.returncode == 0 and caminho else None
    finally:
        _dialogo.release()


def abrir_no_musescore(caminho):
    _soltar(['mscore', caminho])


def abrir(caminho):
    """Abre arquivo ou pasta com o programa padrão (PDF no leitor, pasta no gerenciador de arquivos)."""
    _soltar(['gio', 'open', caminho])


def mostrar_na_pasta(caminho):
    """Abre o gerenciador de arquivos com o arquivo selecionado (se der), senão abre a pasta."""
    uri = Path(caminho).resolve().as_uri()
    r = subprocess.run(['gdbus', 'call', '--session', '--dest', 'org.freedesktop.FileManager1',
                        '--object-path', '/org/freedesktop/FileManager1',
                        '--method', 'org.freedesktop.FileManager1.ShowItems', f"['{uri}']", ''],
                       capture_output=True, timeout=5)
    if r.returncode != 0:
        abrir(Path(caminho).parent)


def notificar(titulo, texto):
    if shutil.which('notify-send'):
        _soltar(['notify-send', '--app-name=Central de Partituras', '--icon=audio-x-generic', titulo, texto])
