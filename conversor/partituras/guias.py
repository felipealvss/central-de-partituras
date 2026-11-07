"""Guias de altura: o nome das notas (Mi2, Dó2, Lá1...) desenhado nas linhas suplementares de cada pauta,
usando as linhas detectadas pelo Audiveris (.omr). Facilita contar linhas suplementares na revisão."""
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LETRAS = 'CDEFGAB'
FONTE = '/usr/share/fonts/liberation-sans-fonts/LiberationSans-Bold.ttf'


def _y_em(pts, x):
    for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
        if xa <= x <= xb:
            return ya + (yb - ya) * (x - xa) / (xb - xa)
    return pts[0][1] if x < pts[0][0] else pts[-1][1]


def gerar(omr, imagens, clave, pasta):
    """omr: arquivo .omr do Audiveris; imagens: as páginas preparadas que ele leu; clave: 'fa' ou 'sol'.
    Grava pagina<N>-sistema<M>-a/b.jpg em `pasta` e devolve a lista de arquivos."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    base = 2 * 7 + 4 if clave == 'fa' else 4 * 7 + 2  # linha inferior: Sol2 (fá) ou Mi4 (sol)
    try:
        fonte = ImageFont.truetype(FONTE, 17)
    except OSError:
        fonte = ImageFont.load_default()
    feitos = []
    z = zipfile.ZipFile(omr)
    for folha, img in enumerate(imagens, 1):
        nome_xml = f'sheet#{folha}/sheet#{folha}.xml'
        if nome_xml not in z.namelist():
            continue
        raiz = ET.fromstring(z.read(nome_xml))
        im = Image.open(img).convert('RGB')
        d = ImageDraw.Draw(im, 'RGBA')
        for n, staff in enumerate(raiz.iter('staff'), 1):
            linhas = [[(float(p.get('x')), float(p.get('y'))) for p in l.iter('point')] for l in staff.iter('line')]
            if len(linhas) != 5:
                continue
            topo, fundo = linhas[0], linhas[4]
            x0, x1 = int(float(staff.get('left'))), int(float(staff.get('right')))
            inter = (_y_em(fundo, x0) - _y_em(topo, x0)) / 4
            for k in range(-11, 20):
                if 0 <= k <= 8 and k % 2 == 0:
                    continue  # linhas reais da pauta
                idx = base + k
                rotulo = LETRAS[idx % 7] + str(idx // 7)
                linha_sup = k % 2 == 0
                if k < 0 or k > 8:
                    pts = [(x, _y_em(fundo, x) - k * (_y_em(fundo, x) - _y_em(topo, x)) / 8) for x in range(x0, x1 + 1, 40)]
                    d.line(pts, fill=(220, 30, 30, 150) if linha_sup else (30, 90, 220, 90), width=2 if linha_sup else 1)
                for xl in range(max(x0 - 60, 0), x1, 420):
                    y = _y_em(fundo, xl) - k * (_y_em(fundo, xl) - _y_em(topo, xl)) / 8
                    d.text((xl + 2, y - 9), rotulo, font=fonte, fill=(200, 0, 120, 255) if linha_sup else (0, 90, 200, 255))
            ya = min(p[1] for p in topo) - 6 * inter
            yb = max(p[1] for p in fundo) + 6.5 * inter
            meio = (x0 + x1) // 2
            for lado, (a, b) in zip('ab', [(0, meio + 120), (meio - 120, im.width)]):
                destino = pasta / f'pagina{folha}-sistema{n}-{lado}.jpg'
                im.crop((a, max(int(ya), 0), b, min(int(yb), im.height))).save(destino, quality=88)
                feitos.append(destino)
    return feitos
