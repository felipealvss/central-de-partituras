# Conversor — guia técnico

Para **usar** a Central de Partituras, veja o manual: `../MANUAL.md` (ou a aba **Ajuda** dentro do programa).
Este arquivo descreve o código, para quem for mexer nele.

## Instalação

```
./instalar.sh            # ambiente Python, Audiveris, dados de OCR e (opcional) atalho no menu
../abrir-conversor.sh    # abre a interface
```

Tudo fica dentro desta pasta: `.venv/` (Python 3.14 com homr, Flask, waitress…), `audiveris/` (extraído do .deb oficial), `tessdata/` (OCR). O estado do programa fica em `../.estado/`.

## Estrutura

| Arquivo | Função |
|---|---|
| `converter.py` / `converter` | linha de comando (mesmo núcleo da interface) |
| `partituras/pipeline.py` | fases: `reconhecer` (motor, lento) → `acabar` (correções e conferência, segundos) → `publicar` |
| `partituras/motores.py` | homr e Audiveris (o Audiveris com `XDG_*` dentro de `.estado/`) |
| `partituras/musicxml.py` | juntar páginas, pausas longas, ligaduras de valor (+ acidente), trechos de pausa e correção, cabeçalho |
| `partituras/conferencia.py` | relatório como dados (mapa de compassos) e como texto |
| `partituras/publicar.py` | publicação que nunca sobrescreve (`os.link` exclusivo; "Nome (2)") |
| `partituras/processos.py` | programas externos com limite de tempo; encerramento do grupo de processos |
| `partituras/biblioteca.py` / `fotos.py` | músicas (`musica.json`, gravação atômica, revisão/409), caixa de entrada, EXIF, miniaturas, grupos |
| `partituras/fila.py` / `trabalho.py` | fila: cada conversão num processo separado; progresso em linhas JSON |
| `partituras/servidor.py` | API Flask + waitress (127.0.0.1, ficha → cookie, `Host`, `X-Central`), instância única |
| `partituras/exportar.py` / `revisao.py` | .zip unificado; pacote de revisão com o Claude |
| `partituras/notacao.py` | notação compacta → MusicXML (transcrições assistidas) |
| `partituras/static/` | interface (HTML/CSS/JS sem framework; cores da paleta validada da skill dataviz) |
| `ferramentas/` | `gerar_manual.py` (MANUAL.pdf), `guias.py` e `listar_mxl.py` (ferramentas da revisão) |
| `testes/` | `unittest`; as saídas reais dos motores ficam em `testes/dados/`, fora do repositório (ver Testes) |

## Testes

```
.venv/bin/python -m unittest discover -s testes -v
```

As referências em `testes/dados/` são leituras reais de uma partitura protegida por direitos autorais (homr, Audiveris e a transcrição revisada) e não vão para o repositório. Sem elas, os testes que as usam são pulados; os demais rodam normalmente.

Cobrem: pausas longas nos formatos do homr e do Audiveris; ligaduras de valor com acidente; correção dos trechos de pausa (com os números certos, o resultado do homr bate 33/33 compassos com notas com a transcrição revisada); conferência igual à de referência; publicação sem sobrescrever (inclusive em sistema de arquivos sem links); cancelamento que encerra processos-netos; biblioteca com edição concorrente; servidor (ficha, `Host`, cabeçalho, caminhos com `../`); fila com trabalhador falso; .zip.

## Manual em PDF

```
.venv/bin/python ferramentas/gerar_manual.py     # MANUAL.md → ../MANUAL.pdf
```
