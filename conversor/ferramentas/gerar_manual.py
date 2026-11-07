"""Gera MANUAL.pdf a partir de MANUAL.md (com as capturas de tela), usando o Chrome sem janela.

Uso (na pasta conversor/): .venv/bin/python ferramentas/gerar_manual.py
"""
import html
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

CSS = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm; }
body { font: 10.5pt/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; color: #0b0b0b; }
h1 { font-size: 22pt; margin: 0 0 4mm; } h2 { font-size: 14.5pt; margin: 8mm 0 2.5mm; break-after: avoid; }
p, li { margin: 1.4mm 0; } ul, ol { padding-left: 6mm; }
code { background: #f0efec; padding: 0 3px; border-radius: 3px; font-size: 9.5pt; }
pre { background: #f0efec; padding: 3mm; border-radius: 4px; font-size: 8.8pt; white-space: pre-wrap; break-inside: avoid; }
table { border-collapse: collapse; margin: 3mm 0; width: 100%; break-inside: avoid; }
th, td { border: 1px solid #e1e0d9; padding: 1.6mm 2.4mm; text-align: left; vertical-align: top; }
th { background: #f9f9f7; }
img { display: block; max-width: 100%; max-height: 110mm; margin: 3mm auto 4mm; border: 1px solid #e1e0d9; border-radius: 4px; break-inside: avoid; }
.capa { color: #52514e; margin-bottom: 6mm; }
"""


def inline(texto):
    t = html.escape(texto)
    t = re.sub(r'`([^`]+)`', r'<code>\1</code>', t)
    t = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', t)
    return re.sub(r'(^|[^*])\*([^*]+)\*', r'\1<em>\2</em>', t)


def para_html(md):
    saida, lista, tabela, codigo = [], None, None, None

    def fechar():
        nonlocal lista, tabela
        if lista:
            saida.append(f"<{lista[0]}>" + ''.join(f'<li>{i}</li>' for i in lista[1]) + f"</{lista[0]}>")
            lista = None
        if tabela:
            linhas = ''.join('<tr>' + ''.join(f'<{"th" if i == 0 else "td"}>{c}</{"th" if i == 0 else "td"}>' for c in l) + '</tr>'
                             for i, l in enumerate(tabela))
            saida.append(f'<table>{linhas}</table>')
            tabela = None

    for linha in md.splitlines():
        if linha.startswith('```'):
            if codigo is None:
                fechar()
                codigo = []
            else:
                saida.append(f'<pre>{html.escape(chr(10).join(codigo))}</pre>')
                codigo = None
            continue
        if codigo is not None:
            codigo.append(linha)
            continue
        if m := re.match(r'^!\[([^\]]*)\]\(([^)]+)\)\s*$', linha):
            fechar()
            saida.append(f'<img src="{(RAIZ / m[2]).as_uri()}" alt="{html.escape(m[1])}">')
        elif m := re.match(r'^(#{1,4})\s+(.*)', linha):
            fechar()
            saida.append(f'<h{len(m[1])}>{inline(m[2])}</h{len(m[1])}>')
        elif m := re.match(r'^\s*[-*]\s+(.*)', linha):
            if not lista or lista[0] != 'ul':
                fechar()
                lista = ['ul', []]
            lista[1].append(inline(m[1]))
        elif m := re.match(r'^\s*\d+[.)]\s+(.*)', linha):
            if not lista or lista[0] != 'ol':
                fechar()
                lista = ['ol', []]
            lista[1].append(inline(m[1]))
        elif linha.strip().startswith('|'):
            if re.match(r'^\s*\|[\s:|-]+\|\s*$', linha):
                continue
            if tabela is None:
                fechar()
                tabela = []
            tabela.append([inline(c.strip()) for c in linha.strip().strip('|').split('|')])
        elif not linha.strip():
            fechar()
        else:
            fechar()
            saida.append(f'<p>{inline(linha)}</p>')
    fechar()
    return '\n'.join(saida)


def main():
    md = (RAIZ / 'MANUAL.md').read_text(encoding='utf-8')
    corpo = para_html(md)
    pagina = f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Central de Partituras — manual</title><style>{CSS}</style></head><body>{corpo}</body></html>'
    tmp = Path(tempfile.mkdtemp(prefix='manual-'))
    try:
        arq = tmp / 'manual.html'
        arq.write_text(pagina, encoding='utf-8')
        destino = RAIZ / 'MANUAL.pdf'
        chrome = shutil.which('google-chrome') or shutil.which('chromium') or shutil.which('chromium-browser')
        subprocess.run([chrome, '--headless=new', '--disable-gpu', '--no-first-run', f'--user-data-dir={tmp / "perfil"}',
                        '--no-pdf-header-footer', f'--print-to-pdf={destino}', arq.as_uri()],
                       check=True, capture_output=True, timeout=120)
        print(f'Manual gerado: {destino}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
