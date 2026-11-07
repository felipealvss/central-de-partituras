"""Leitura e preparação das páginas: fotos (HEIC/JPG/PNG...) ou PDF."""
import math
import subprocess
from pathlib import Path

import numpy as np
import pillow_heif
from PIL import Image, ImageFilter, ImageOps

from .erros import ErroConversao

pillow_heif.register_heif_opener()

EXTENSOES_IMAGEM = {'.heic', '.heif', '.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp', '.bmp'}
EXTENSOES = EXTENSOES_IMAGEM | {'.pdf'}
# Distância entre linhas da pauta (px) entregue ao Audiveris. Em fotos de celular (~22 px) ele não reconheceu
# cabeças de nota vazias numa das páginas; ampliando para ~32 px passou a reconhecer parte delas.
INTERLINHA_ALVO = 32
# O Audiveris recusa páginas com mais de 20 milhões de pixels ("Too large image"): fotos de câmeras de 37 MP
# ou mais são reduzidas até este limite, com folga.
PIXELS_MAX_AUDIVERIS = 18_000_000


def fator_audiveris(largura, altura, interlinha):
    """Escala da página para o Audiveris: amplia até a interlinha alvo (no máximo 3x), mas sem passar do limite
    de pixels por página — nesse caso reduz, mesmo que a interlinha fique abaixo do alvo."""
    fator = 1.0 if not interlinha else min(max(INTERLINHA_ALVO / interlinha, 1.0), 3.0)
    return min(fator, math.sqrt(PIXELS_MAX_AUDIVERIS / (largura * altura)))


def abrir_imagem(caminho, giro=0):
    """Abre corrigindo a orientação do EXIF; `giro` em graus, sentido horário (0, 90, 180, 270)."""
    try:
        im = ImageOps.exif_transpose(Image.open(caminho))
    except Exception as e:
        raise ErroConversao(f'Não consegui abrir a imagem "{Path(caminho).name}": {e}')
    if giro % 360:
        im = im.rotate(-(giro % 360), expand=True)
    return im


def pdf_para_imagens(pdf, pasta, dpi=300):
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    prefixo = pasta / f'pdf-{abs(hash(str(pdf))) % 10**8}'
    r = subprocess.run(['pdftoppm', '-r', str(dpi), '-gray', '-png', str(pdf), str(prefixo)], capture_output=True, text=True)
    paginas = sorted(pasta.glob(prefixo.name + '-*.png'))
    if r.returncode != 0 or not paginas:
        raise ErroConversao(f'Não consegui ler o PDF "{Path(pdf).name}": {r.stderr.strip()}')
    return paginas


def carregar(paginas, pasta):
    """paginas: lista de objetos com .caminho e .giro. Devolve [(nome, Image)] na ordem."""
    imagens = []
    for pg in paginas:
        caminho = Path(pg.caminho)
        if not caminho.exists():
            raise ErroConversao(f'Arquivo não encontrado: {caminho}')
        if caminho.suffix.lower() == '.pdf':
            for i, f in enumerate(pdf_para_imagens(caminho, pasta), 1):
                imagens.append((f'{caminho.name} p.{i}', abrir_imagem(f, pg.giro)))
        else:
            imagens.append((caminho.name, abrir_imagem(caminho, pg.giro)))
    if not imagens:
        raise ErroConversao('Nenhuma página para converter.')
    return imagens


def recortar_papel(g):
    """Remove o fundo escuro em volta da folha (mesa, sombra)."""
    a = np.asarray(g.filter(ImageFilter.GaussianBlur(6)))
    claro = a > 115
    linhas = np.where(claro.mean(axis=1) > 0.5)[0]
    colunas = np.where(claro.mean(axis=0) > 0.5)[0]
    if len(linhas) < 100 or len(colunas) < 100:
        return g
    return g.crop((int(colunas[0]), int(linhas[0]), int(colunas[-1]) + 1, int(linhas[-1]) + 1))


def estimar_interlinha(g):
    """Distância entre linhas da pauta por autocorrelação, em faixas verticais estreitas
    (assim uma foto levemente torta não borra as linhas)."""
    escuro = (np.asarray(g, dtype=np.float32) < 128).astype(np.float32)
    h, w = escuro.shape
    medidas = []
    for x0 in range(int(w * 0.1), int(w * 0.9) - 150, 150):
        p = escuro[:, x0:x0 + 150].mean(axis=1)
        p = p - p.mean()
        f = np.fft.rfft(p, 2 * len(p))
        ac = np.fft.irfft(f * np.conj(f))[:len(p)]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        lag = int(np.argmax(ac[8:120])) + 8
        if ac[lag] > 0.15:
            medidas.append(lag)
    return float(np.median(medidas)) if medidas else None


def preparar_audiveris(imagens, pasta, avisar=print):
    """Recorta, ajusta a escala (interlinha alvo, sem passar do limite de pixels do Audiveris) e junta tudo
    num PDF sem perda (as páginas viram uma obra só)."""
    pasta = Path(pasta)
    arquivos, info = [], []
    for i, (nome, im) in enumerate(imagens, 1):
        g = recortar_papel(im.convert('L'))
        inter = estimar_interlinha(g)
        fator = fator_audiveris(g.width, g.height, inter)
        if abs(fator - 1) > 0.01:
            g = g.resize((round(g.width * fator), round(g.height * fator)), Image.LANCZOS)
        g = ImageOps.autocontrast(g, cutoff=1)
        g.info.pop('icc_profile', None)  # perfil de cor RGB da foto não vale para tons de cinza
        f = pasta / f'pagina{i:02d}.png'
        g.save(f)
        arquivos.append(f)
        info.append({'pagina': i, 'nome': nome, 'interlinha': inter, 'ampliacao': round(fator, 2)})
        escala = f'ampliação {fator:.2f}x' if fator >= 1 else f'redução {fator:.2f}x (limite de pixels do Audiveris)'
        avisar(f'página {i}: interlinha {inter:.0f} px, {escala}' if inter else f'página {i}: interlinha não medida, {escala}')
    pdf = pasta / 'partitura.pdf'
    r = subprocess.run(['magick', *map(str, arquivos), '-compress', 'Zip', '-density', '300', str(pdf)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not pdf.exists():
        raise ErroConversao(f'Falha ao preparar as páginas para o Audiveris: {r.stderr.strip()}')
    return pdf, arquivos, info


def salvar_jpeg(im, destino, qualidade=92, lado_max=None):
    im = im.convert('RGB')
    if lado_max and max(im.size) > lado_max:
        im.thumbnail((lado_max, lado_max), Image.LANCZOS)
    im.save(destino, quality=qualidade)
    return destino
