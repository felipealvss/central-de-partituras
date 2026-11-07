#!/usr/bin/env python3
"""Converte fotos ou PDF de partitura em arquivo do MuseScore (.mscz).

Etapas: preparar as imagens -> reconhecer (homr ou Audiveris) -> ajustar o MusicXML ->
conferir os compassos -> converter com o MuseScore.

Motores:
  homr       (padrão) feito para fotos de celular; no teste acertou 32 de 33 compassos com notas,
             mas não gera ligaduras, dinâmicas nem textos.
  audiveris  lê dinâmicas, articulações e textos; com fotos de celular perdeu semibreves graves.

Uso (pelo atalho ./converter):
    ./converter pagina1.heic pagina2.heic -o "Minha musica.mscz"
    ./converter partitura.pdf -o musica.mscz --motor audiveris --titulo "Hino 15" --pdf --guias fa
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pillow_heif
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

pillow_heif.register_heif_opener()

AQUI = Path(__file__).resolve().parent
AUDIVERIS = AQUI / 'audiveris' / 'opt' / 'audiveris' / 'bin' / 'Audiveris'
TESSDATA = AQUI / 'tessdata'
# Distância entre linhas da pauta, em pixels, entregue ao Audiveris. Em fotos de celular (~22 px) ele não
# reconheceu cabeças de nota vazias numa das páginas; ampliando para ~32 px passou a reconhecer parte delas.
# Semibreves com várias linhas suplementares continuaram falhando: por isso o relatório de conferência.
INTERLINHA_ALVO = 32


def avisar(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- imagens

def carregar_paginas(entradas, tmp):
    paginas = []
    for entrada in entradas:
        entrada = Path(entrada)
        if not entrada.exists():
            sys.exit(f'Arquivo não encontrado: {entrada}')
        if entrada.suffix.lower() == '.pdf':
            prefixo = tmp / f'pdf{len(paginas):02d}'
            subprocess.run(['pdftoppm', '-r', '300', '-gray', '-png', str(entrada), str(prefixo)], check=True)
            for i, f in enumerate(sorted(tmp.glob(prefixo.name + '-*.png')), 1):
                paginas.append((f'{entrada.name} p.{i}', Image.open(f)))
        else:
            paginas.append((entrada.name, ImageOps.exif_transpose(Image.open(entrada))))
    return paginas


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
    """Mede a distância entre linhas da pauta por autocorrelação, em faixas verticais estreitas
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


def preparar(paginas, tmp):
    arquivos = []
    for i, (nome, im) in enumerate(paginas, 1):
        g = recortar_papel(im.convert('L'))
        inter = estimar_interlinha(g)
        fator = 1.0 if not inter else min(max(INTERLINHA_ALVO / inter, 1.0), 3.0)
        if fator > 1.01:
            g = g.resize((round(g.width * fator), round(g.height * fator)), Image.LANCZOS)
        g = ImageOps.autocontrast(g, cutoff=1)
        txt = f'{inter:.0f} px' if inter else 'não medida'
        avisar(f'  página {i} ({nome}): interlinha {txt}, ampliação {fator:.2f}x -> {g.width}x{g.height}')
        f = tmp / f'pagina{i:02d}.png'
        g.info.pop('icc_profile', None)  # perfil de cor RGB da foto não vale para imagem em tons de cinza
        g.save(f)
        arquivos.append(f)
    pdf = tmp / 'partitura.pdf'
    # PDF sem perda: todas as páginas viram um único "livro" no Audiveris (o compasso da 1ª página vale para as seguintes).
    subprocess.run(['magick', *map(str, arquivos), '-compress', 'Zip', '-density', '300', str(pdf)], check=True)
    return pdf, arquivos


# ---------------------------------------------------------------- homr

def reconhecer_homr(paginas, tmp):
    """Roda o homr em cada página (ele trabalha página a página) e devolve as árvores MusicXML."""
    homr = Path(sys.executable).parent / 'homr'
    if not homr.exists():
        sys.exit('homr não instalado. Rode ./instalar.sh de novo.')
    arvores = []
    for i, (nome, im) in enumerate(paginas, 1):
        img = tmp / f'homr-pagina{i:02d}.jpg'
        im.convert('RGB').save(img, quality=95)
        avisar(f'  página {i} ({nome})...')
        r = subprocess.run([str(homr), str(img)], capture_output=True, text=True, cwd=tmp)
        (tmp / f'homr-pagina{i:02d}.log').write_text(r.stdout + r.stderr, encoding='utf-8')
        xml = img.with_suffix('.musicxml')
        if not xml.exists():
            sys.exit(f'O homr não reconheceu a página {i}. Veja o log com --manter.')
        arvores.append(ET.parse(xml))
    return arvores


def unir_paginas(arvores):
    """Junta as páginas reconhecidas separadamente numa partitura só, sem repetir clave,
    armadura ou fórmula de compasso iguais às anteriores."""
    base = arvores[0]
    parte = base.getroot().find('part')
    atual = {}

    def registrar(m):
        for at in m.findall('attributes'):
            for tag in ('key', 'time', 'clef'):
                el = at.find(tag)
                if el is not None:
                    atual[tag] = ET.tostring(el)

    for m in parte.findall('measure'):
        registrar(m)
    for arv in arvores[1:]:
        medidas = arv.getroot().find('part').findall('measure')
        for i, m in enumerate(medidas):
            if i == 0:
                m.insert(0, ET.Element('print', {'new-page': 'yes'}))
                for at in m.findall('attributes'):
                    for tag in ('key', 'time', 'clef'):
                        el = at.find(tag)
                        if el is not None and atual.get(tag) == ET.tostring(el):
                            at.remove(el)
            registrar(m)
            parte.append(m)
    return base


# ---------------------------------------------------------------- Audiveris

def reconhecer(pdf, tmp):
    if not AUDIVERIS.exists():
        sys.exit('Audiveris não instalado. Rode ./instalar.sh primeiro.')
    saida = tmp / 'omr'
    saida.mkdir()
    env = dict(os.environ, TESSDATA_PREFIX=str(TESSDATA))
    r = subprocess.run([str(AUDIVERIS), '-batch', '-export', '-output', str(saida), '--', str(pdf)],
                       capture_output=True, text=True, env=env)
    (tmp / 'audiveris.log').write_text(r.stdout + r.stderr, encoding='utf-8')
    mxls = sorted(saida.glob('*.mxl'))
    if not mxls:
        sys.exit(f'O Audiveris não gerou partitura. Veja o log em {tmp / "audiveris.log"} (use --manter).')
    omr = next(iter(saida.glob('*.omr')), None)
    return mxls, omr


def ler_mxl(mxl):
    z = zipfile.ZipFile(mxl)
    raiz_nome = None
    if 'META-INF/container.xml' in z.namelist():
        cont = ET.fromstring(z.read('META-INF/container.xml'))
        rf = cont.find('.//{*}rootfile')
        if rf is not None:
            raiz_nome = rf.get('full-path')
    if not raiz_nome:
        raiz_nome = next(n for n in z.namelist() if n.endswith('.xml') and not n.startswith('META-INF'))
    return ET.ElementTree(ET.fromstring(z.read(raiz_nome)))


def ajustar(arvore, titulo, instrumento, compositor):
    """Remove os textos de cabeçalho lidos pelo OCR (saem desalinhados no MuseScore), define título e
    nome do instrumento. Devolve os textos removidos, para o relatório."""
    raiz = arvore.getroot()
    textos = []
    for credito in raiz.findall('credit'):
        for cw in credito.iter('credit-words'):
            t = (cw.text or '').strip()
            if t:
                textos.append((float(cw.get('font-size') or 0), t))
        raiz.remove(credito)
    # O Audiveris também espalha o OCR por título de movimento e créditos, e grava caminhos temporários.
    for tag in ('movement-number', 'movement-title'):
        for el in raiz.findall(tag):
            raiz.remove(el)
    ident = raiz.find('identification')
    if ident is not None:
        for el in ident.findall('creator') + ident.findall('source') + ident.findall('miscellaneous'):
            ident.remove(el)
        if compositor:
            cr = ET.Element('creator', type='composer')
            cr.text = compositor
            ident.insert(0, cr)
    if not titulo and textos:
        titulo = max(textos)[1]
    if titulo:
        work = raiz.find('work')
        if work is None:
            work = ET.Element('work')
            raiz.insert(0, work)
        wt = work.find('work-title')
        if wt is None:
            wt = ET.SubElement(work, 'work-title')
        wt.text = titulo
    if instrumento:
        for tag in ('part-name', 'part-abbreviation', 'instrument-name'):
            for el in raiz.iter(tag):
                el.text = instrumento
    return [t for _, t in textos]


# ---------------------------------------------------------------- conferência

def so_pausa(m):
    return all(n.find('rest') is not None for n in m.findall('note'))


def normalizar_multirests(arvore):
    """Garante que cada pausa de N compassos tenha N compassos reais (o homr grava só um),
    e renumera os compassos."""
    for parte in arvore.getroot().iter('part'):
        medidas = parte.findall('measure')
        i = 0
        while i < len(medidas):
            mr = medidas[i].find('attributes/measure-style/multiple-rest')
            if mr is not None and (mr.text or '').strip().isdigit():
                n, j = int(mr.text), i + 1
                # Audiveris escreve os N compassos (com pausa); o homr escreve um só compasso, sem notas.
                if medidas[i].find('note') is not None:
                    while (j < len(medidas) and j - i < n and so_pausa(medidas[j])
                           and medidas[j].find('attributes/measure-style/multiple-rest') is None):
                        j += 1
                pos = list(parte).index(medidas[j - 1]) + 1
                for _ in range(n - (j - i)):
                    parte.insert(pos, ET.Element('measure'))
                medidas = parte.findall('measure')
                i += n
            else:
                i += 1
        for k, m in enumerate(parte.findall('measure'), 1):
            m.set('number', str(k))

def conferir(arvore):
    """Lista compassos com duração diferente da fórmula de compasso e compassos só com pausa
    (onde o Audiveris costuma esconder semibreves que não reconheceu)."""
    raiz = arvore.getroot()
    linhas, so_pausa, multirests = [], [], []
    total = 0
    for parte in raiz.iter('part'):
        divisoes, beats, beat_type = 1, 4, 4
        for numero, m in enumerate(parte.iter('measure'), 1):
            total += 1
            for at in m.iter('attributes'):
                if at.findtext('divisions'):
                    divisoes = int(at.findtext('divisions'))
                if at.find('time') is not None and at.findtext('time/beats'):
                    beats, beat_type = int(at.findtext('time/beats')), int(at.findtext('time/beat-type'))
                mr = at.findtext('measure-style/multiple-rest')
                if mr:
                    multirests.append((numero, int(mr)))
            esperado = beats * divisoes * 4 // beat_type
            pos, maximo, tem_nota, pausa_inteira = 0, 0, False, False
            for el in m:
                if el.tag == 'note':
                    if el.find('grace') is not None or el.find('chord') is not None:
                        continue
                    if el.find('rest') is not None and el.find('rest').get('measure') == 'yes':
                        pausa_inteira = True
                    if el.find('rest') is None:
                        tem_nota = True
                    pos += int(el.findtext('duration') or 0)
                elif el.tag == 'backup':
                    pos -= int(el.findtext('duration') or 0)
                elif el.tag == 'forward':
                    pos += int(el.findtext('duration') or 0)
                maximo = max(maximo, pos)
            if not tem_nota:
                so_pausa.append(numero)
            elif not pausa_inteira and maximo != esperado:
                linhas.append(f'  compasso {numero}: duração {maximo / divisoes:g} tempos, esperado {esperado / divisoes:g}')
    rel = [f'Compassos no arquivo: {total} (compare com o último número de compasso impresso na partitura;'
           ' se faltar, alguma pausa longa ou nota foi lida errado)']
    if multirests:
        rel.append('Pausas de vários compassos (confira os números com a partitura: os de dois dígitos costumam sair errados):')
        rel.append('  ' + ', '.join(f'c.{n}: {q}' for n, q in multirests))
    rel.append('Compassos com duração errada (nota ou figura mal reconhecida):')
    rel.extend(linhas or ['  nenhum'])
    rel.append('Compassos só com pausa (confira se não havia semibreves ali):')
    rel.append('  ' + (', '.join(map(str, so_pausa)) if so_pausa else 'nenhum'))
    return '\n'.join(rel)


# ---------------------------------------------------------------- guias de altura

def gerar_guias(omr, imagens, clave, pasta):
    """Desenha guias com o nome das notas abaixo e acima de cada pauta, usando as linhas que o
    Audiveris detectou. Facilita contar linhas suplementares na revisão."""
    pasta.mkdir(parents=True, exist_ok=True)
    base = 2 * 7 + 4 if clave == 'fa' else 4 * 7 + 2  # linha inferior: Sol2 (fá) ou Mi4 (sol)
    letras = 'CDEFGAB'
    try:
        fonte = ImageFont.truetype('/usr/share/fonts/liberation-sans-fonts/LiberationSans-Bold.ttf', 17)
    except OSError:
        fonte = ImageFont.load_default()
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

            def y_em(pts, x):
                for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
                    if xa <= x <= xb:
                        return ya + (yb - ya) * (x - xa) / (xb - xa)
                return pts[0][1] if x < pts[0][0] else pts[-1][1]

            x0, x1 = int(float(staff.get('left'))), int(float(staff.get('right')))
            inter = (y_em(fundo, x0) - y_em(topo, x0)) / 4
            for k in range(-11, 20):
                if 0 <= k <= 8 and k % 2 == 0:
                    continue
                idx = base + k
                rotulo = letras[idx % 7] + str(idx // 7)
                linha_sup = k % 2 == 0
                if k < 0 or k > 8:
                    pts = [(x, y_em(fundo, x) - k * (y_em(fundo, x) - y_em(topo, x)) / 8) for x in range(x0, x1 + 1, 40)]
                    d.line(pts, fill=(220, 30, 30, 150) if linha_sup else (30, 90, 220, 90), width=2 if linha_sup else 1)
                for xl in range(max(x0 - 60, 0), x1, 420):
                    y = y_em(fundo, xl) - k * (y_em(fundo, xl) - y_em(topo, xl)) / 8
                    d.text((xl + 2, y - 9), rotulo, font=fonte, fill=(200, 0, 120, 255) if linha_sup else (0, 90, 200, 255))
            ya = min(p[1] for p in topo) - 6 * inter
            yb = max(p[1] for p in fundo) + 6.5 * inter
            meio = (x0 + x1) // 2
            for lado, (a, b) in zip('ab', [(0, meio + 120), (meio - 120, im.width)]):
                im.crop((a, max(int(ya), 0), b, min(int(yb), im.height))).save(pasta / f'pagina{folha}-sistema{n}-{lado}.jpg', quality=88)


# ---------------------------------------------------------------- MuseScore

def para_musescore(musicxml, destino, pdf):
    if not shutil.which('mscore'):
        sys.exit('MuseScore (mscore) não encontrado no PATH.')
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    destino.unlink(missing_ok=True)
    subprocess.run(['mscore', '-o', str(destino), str(musicxml)], env=env, capture_output=True)
    if not destino.exists():
        sys.exit('O MuseScore não conseguiu converter o MusicXML.')
    if pdf:
        subprocess.run(['mscore', '-o', str(destino.with_suffix('.pdf')), str(destino)], env=env, capture_output=True)


def main():
    ap = argparse.ArgumentParser(description='Converte fotos (HEIC/JPG/PNG) ou PDF de partitura em .mscz.')
    ap.add_argument('entradas', nargs='+', help='páginas na ordem (fotos ou PDF)')
    ap.add_argument('-o', '--saida', required=True, help='arquivo .mscz de saída')
    ap.add_argument('--titulo', help='título da obra')
    ap.add_argument('--instrumento', help='nome do instrumento/parte')
    ap.add_argument('--compositor', help='compositor/arranjador mostrado no cabeçalho')
    ap.add_argument('--motor', choices=['homr', 'audiveris'], default='homr',
                    help='programa de reconhecimento (padrão: homr, melhor para fotos de celular)')
    ap.add_argument('--pdf', action='store_true', help='também exporta um PDF do resultado, para comparar com o original')
    ap.add_argument('--guias', choices=['fa', 'sol'], help='gera imagens de cada sistema com guias de altura para a clave indicada'
                    ' (usa as linhas de pauta detectadas pelo Audiveris)')
    ap.add_argument('--manter', action='store_true', help='mantém a pasta temporária (logs e imagens preparadas)')
    args = ap.parse_args()

    destino = Path(args.saida).with_suffix('.mscz').resolve()
    tmp = Path(tempfile.mkdtemp(prefix='conversor-omr-'))
    try:
        avisar('1/4 Preparando as imagens...')
        paginas = carregar_paginas(args.entradas, tmp)
        omr = imagens = None
        if args.motor == 'audiveris' or args.guias:
            pdf, imagens = preparar(paginas, tmp)
        if args.motor == 'homr':
            avisar('2/4 Reconhecendo com o homr (na primeira vez ele baixa os modelos)...')
            arvores = [unir_paginas(reconhecer_homr(paginas, tmp))]
            if args.guias:
                avisar('  Rodando o Audiveris só para localizar as pautas das guias...')
                _, omr = reconhecer(pdf, tmp)
        else:
            avisar('2/4 Reconhecendo a partitura com o Audiveris (pode levar alguns minutos)...')
            mxls, omr = reconhecer(pdf, tmp)
            if len(mxls) > 1:
                avisar(f'  O Audiveris dividiu a obra em {len(mxls)} partes; cada uma vira um arquivo.')
            arvores = [ler_mxl(m) for m in mxls]
        avisar('3/4 Conferindo os compassos...')
        relatorios = []
        for i, arvore in enumerate(arvores, 1):
            normalizar_multirests(arvore)
            textos = ajustar(arvore, args.titulo, args.instrumento, args.compositor)
            alvo = destino if len(arvores) == 1 else destino.with_name(f'{destino.stem}-{i}.mscz')
            xml = tmp / f'{alvo.stem}.musicxml'
            arvore.write(xml, encoding='utf-8', xml_declaration=True)
            rel = f'Motor: {args.motor}\n' + conferir(arvore)
            if args.motor == 'homr':
                rel += ('\nO homr não gera dinâmicas, textos nem fermatas, e reconhece só parte dos acentos: acrescente no MuseScore.'
                        '\nLigaduras de valor vêm como ligaduras de expressão: parecem iguais, mas o MuseScore toca a nota de novo.'
                        ' Selecione a nota e troque pela ligadura de valor (tecla +).'
                        '\nEle também ignora que a ligadura mantém o acidente além da barra (ex.: Dó♮ ligado vira Dó♯ no compasso seguinte).')
            if textos:
                rel += '\nTextos de cabeçalho lidos pelo OCR (fora da partitura; confira a grafia e digite no MuseScore):\n  ' + ' | '.join(textos)
            relatorios.append((alvo, rel))
            avisar('4/4 Convertendo para MuseScore...' if i == 1 else '')
            para_musescore(xml, alvo, args.pdf)
        if args.guias and omr:
            gerar_guias(omr, imagens, args.guias, destino.with_name(destino.stem + '-guias'))
        for alvo, rel in relatorios:
            caminho = alvo.with_name(alvo.stem + '-conferencia.txt')
            caminho.write_text(rel + '\n', encoding='utf-8')
            avisar(f'\nPronto: {alvo}\n{rel}\n(relatório salvo em {caminho.name})')
        if args.guias:
            avisar(f'Guias de altura em: {destino.stem}-guias/')
        avisar('\nO reconhecimento nunca é 100%: revise no MuseScore comparando com a partitura original.')
    finally:
        if args.manter:
            avisar(f'Arquivos temporários mantidos em {tmp}')
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
