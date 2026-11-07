"""Fotos: identificação pelo conteúdo, hora em que foram tiradas, miniaturas e sugestão de grupos."""
import hashlib
import re
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image

from .imagens import abrir_imagem

_NOME_COM_DATA = re.compile(r'(20\d{2})(\d{2})(\d{2})[_\-\s]?(\d{2})(\d{2})(\d{2})')


def identificar(caminho):
    """Identificador pelo conteúdo (detecta a mesma foto importada duas vezes)."""
    h = hashlib.sha256()
    with open(caminho, 'rb') as f:
        for bloco in iter(lambda: f.read(1 << 20), b''):
            h.update(bloco)
    return h.hexdigest()[:16]


def hora_da_foto(caminho):
    """(datetime, origem): EXIF DateTimeOriginal (com fração de segundo), senão o nome do arquivo
    (ex.: 20261107_094652.heic), senão a data de modificação do arquivo."""
    caminho = Path(caminho)
    if caminho.suffix.lower() != '.pdf':
        try:
            with Image.open(caminho) as im:
                exif = im.getexif()
                sub = exif.get_ifd(0x8769)
                valor = sub.get(36867) or exif.get(306)
                if valor:
                    dt = datetime.strptime(str(valor).strip(), '%Y:%m:%d %H:%M:%S')
                    fracao = str(sub.get(37521) or '').strip()
                    if fracao.isdigit():
                        dt = dt.replace(microsecond=int(float('0.' + fracao) * 1_000_000))
                    return dt, 'exif'
        except Exception:  # noqa: BLE001 — foto sem EXIF legível: tenta as alternativas
            pass
    m = _NOME_COM_DATA.search(caminho.name)
    if m:
        try:
            return datetime(*map(int, m.groups())), 'nome'
        except ValueError:
            pass
    return datetime.fromtimestamp(caminho.stat().st_mtime), 'arquivo'


def paginas_do_pdf(caminho):
    r = subprocess.run(['pdfinfo', str(caminho)], capture_output=True, text=True)
    m = re.search(r'^Pages:\s+(\d+)', r.stdout, re.M)
    return int(m.group(1)) if m else 1


def miniatura(caminho, giro, lado, cache):
    """JPEG reduzido (o Chrome não abre HEIC), em cache por arquivo/giro/tamanho."""
    caminho = Path(caminho)
    st = caminho.stat()
    chave = hashlib.sha1(f'{caminho}|{st.st_size}|{st.st_mtime_ns}|{giro}|{lado}'.encode()).hexdigest()[:20]
    destino = Path(cache) / f'{chave}.jpg'
    if destino.exists():
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    if caminho.suffix.lower() == '.pdf':
        prefixo = destino.with_suffix('')
        subprocess.run(['pdftoppm', '-f', '1', '-l', '1', '-singlefile', '-jpeg', '-scale-to', str(lado),
                        str(caminho), str(prefixo)], capture_output=True)
        gerado = prefixo.with_suffix('.jpg')
        if gerado.exists() and giro % 360:
            with Image.open(gerado) as im:
                im.rotate(-(giro % 360), expand=True).save(gerado, quality=85)
        return destino if destino.exists() else None
    im = abrir_imagem(caminho, giro)
    im.thumbnail((lado, lado), Image.LANCZOS)
    tmp = destino.with_name(destino.stem + '.parcial.jpg')
    im.convert('RGB').save(tmp, quality=85)
    tmp.replace(destino)
    return destino


def sugerir_grupos(itens, limiar=90):
    """Separa fotos em grupos (prováveis músicas) quando o intervalo entre fotos seguidas passa de `limiar`
    segundos. `itens`: dicionários com 'hora' (ISO). Devolve lista de listas, na ordem do tempo."""
    ordenados = sorted(itens, key=lambda f: f['hora'])
    grupos = []
    anterior = None
    for item in ordenados:
        hora = datetime.fromisoformat(item['hora'])
        if anterior is None or (hora - anterior).total_seconds() > limiar:
            grupos.append([])
        grupos[-1].append(item)
        anterior = hora
    return grupos
