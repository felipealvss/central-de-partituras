# Desenha guias de altura (clave de fá) sobre a página usando as linhas de pauta detectadas pelo Audiveris
# e recorta cada sistema em duas metades para leitura.  Uso: guias.py arquivo.omr folha imagem.png pasta_saida
import sys, zipfile, xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont
omr, folha, img, saida = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
raiz = ET.fromstring(zipfile.ZipFile(omr).read(f'sheet#{folha}/sheet#{folha}.xml'))
im = Image.open(img).convert('RGB'); d = ImageDraw.Draw(im, 'RGBA')
fonte = ImageFont.truetype('/usr/share/fonts/liberation-sans-fonts/LiberationSans-Bold.ttf', 17)
NOMES = 'CDEFGAB'
def nome(k):  # k = passos acima da linha inferior (Sol2) em clave de fá
    idx = 2 * 7 + 4 + k          # Sol2 = oitava 2, índice 4
    return NOMES[idx % 7] + str(idx // 7)
def interp(pts, x):
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1: return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[0][1] if x < pts[0][0] else pts[-1][1]
n = 0
for staff in raiz.iter('staff'):
    linhas = [[(float(p.get('x')), float(p.get('y'))) for p in l.iter('point')] for l in staff.iter('line')]
    if len(linhas) != 5: continue
    n += 1
    top, bot = linhas[0], linhas[4]
    x0, x1 = int(float(staff.get('left'))), int(float(staff.get('right')))
    for k in range(-11, 10):
        if 0 <= k <= 8 and k % 2 == 0: continue   # linhas reais da pauta
        cor = (220, 30, 30, 150) if k % 2 == 0 else (30, 90, 220, 90)
        pts = []
        for x in range(x0, x1 + 1, 40):
            yb, yt = interp(bot, x), interp(top, x)
            pts.append((x, yb - k * (yb - yt) / 8))
        if k < 0 or k > 8:
            d.line(pts, fill=cor, width=2 if k % 2 == 0 else 1)
        for xl in range(x0 - 60, x1, 420):
            xx = max(xl, 0); yb, yt = interp(bot, xx), interp(top, xx)
            d.text((xx + 2, yb - k * (yb - yt) / 8 - 9), nome(k), fill=(200, 0, 120, 255) if k % 2 == 0 else (0, 90, 200, 255), font=fonte)
    yt0 = min(p[1] for p in top) - 4.5 * 33; yb0 = max(p[1] for p in bot) + 6.5 * 33
    meio = (x0 + x1) // 2
    for i, (a, b) in enumerate([(0, meio + 120), (meio - 120, im.width)]):
        im.crop((a, int(yt0), b, int(yb0))).save(f'{saida}/f{folha}-s{n}-{"ab"[i]}.jpg', quality=88)
print(f'folha {folha}: {n} pautas')
