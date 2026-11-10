# Conversor — guia técnico

Para **usar** a Central de Partituras, veja o manual: `../MANUAL.md` (ou a aba **Ajuda** dentro do programa).
Este arquivo descreve o código, para quem for mexer nele.

## Instalação

```
./instalar.sh                      # ambiente Python, Audiveris, dados de OCR e (opcional) atalho no menu
./instalar.sh --audio              # e o modo de áudio (opcional, ~7,5 GB)
./instalar.sh --atualizar-yt-dlp   # só atualiza o yt-dlp (importar por link quebra quando o site muda)
../abrir-conversor.sh              # abre a interface
```

Tudo fica dentro desta pasta: `.venv/` (Python 3.14 com homr, Flask, waitress…), `audiveris/` (extraído do .deb oficial), `tessdata/` (OCR). O estado do programa fica em `../.estado/`.

O modo de áudio acrescenta `.venv-audio/` (Python 3.12 com PyTorch/CUDA, librosa, music21, Beat This!, yt-dlp), `.uv/python/` (o Python 3.12 que o uv baixou; o `.venv-audio` depende dele) e `modelos-audio/` (os dois modelos, o marcador `.verificado` e o `node.txt`). As versões vêm do `requisitos-audio.txt`, com o hash de cada roda: ele é gerado do `requisitos-audio.in` por `ferramentas/requisitos_audio.py` (as versões são as do ambiente validado no piloto). O `partituras/audio/instalar.py` baixa as rodas que faltam no `.venv-audio` e os modelos (com o `aria2c` em várias conexões, quando existe, ou com o `curl`), confere o SHA-256 de tudo, e o uv instala sem rede (`--offline --no-index`). Motivo: numa conexão que às vezes limita cada download a ~200 KB/s, o uv sozinho chegou a ficar horas parado num download empacado, sem mostrar nada; o aria2c refaz as conexões que travam e retoma o que foi interrompido. Rodar o instalador de novo só baixa o que mudou (com tudo instalado, leva uns 10 s); só o yt-dlp vem pelo uv, da internet, sempre na versão mais nova.

## Estrutura

| Arquivo | Função |
|---|---|
| `converter.py` / `converter` | linha de comando (mesmo núcleo da interface) |
| `partituras/pipeline.py` | fases: `reconhecer` (motor, lento) → `acabar` (correções e conferência, segundos) → `publicar` |
| `partituras/motores.py` / `imagens.py` | homr e Audiveris (o Audiveris com `XDG_*` dentro de `.estado/`); preparo das páginas (interlinha alvo, no máximo 18 Mpx por página, limite do Audiveris) |
| `partituras/musicxml.py` | juntar páginas, pausas longas, ligaduras de valor (+ acidente), trechos de pausa e correção (número de compassos ou grupos com fórmula de compasso própria), cabeçalho |
| `partituras/conferencia.py` | relatório como dados (mapa de compassos) e como texto |
| `partituras/publicar.py` | publicação que nunca sobrescreve (`os.link` exclusivo; "Nome (2)") |
| `partituras/processos.py` | programas externos com limite de tempo; encerramento do grupo de processos |
| `partituras/biblioteca.py` / `fotos.py` | músicas (`musica.json`, gravação atômica, revisão/409), caixa de entrada, EXIF, miniaturas, grupos |
| `partituras/fila.py` / `trabalho.py` | fila: cada conversão num processo separado; progresso em linhas JSON |
| `partituras/servidor.py` | API Flask + waitress (127.0.0.1, ficha → cookie, `Host`, `X-Central`), instância única |
| `partituras/exportar.py` / `revisao.py` | .zip unificado; pacote de revisão com o Claude (sem guias, com aviso, se o Audiveris falhar) |
| `partituras/notacao.py` | notação compacta → MusicXML (transcrições assistidas) |
| `partituras/static/` | interface (HTML/CSS/JS sem framework; cores da paleta validada da skill dataviz) |
| `ferramentas/` | `gerar_manual.py` (MANUAL.pdf), `guias.py` e `listar_mxl.py` (ferramentas da revisão), `requisitos_audio.py` (gera o `requisitos-audio.txt`) |
| `partituras/audio/` | modo de áudio. Leves (rodam no servidor): `instrumentos` (o parâmetro central: stem, faixa de busca, segmentação, transposição, clave, som), `fonte` (ffprobe, hash), `disponivel`, `mega53` (hiperparâmetros e arquivos com SHA-256), `baixar` (yt-dlp), `trabalho` (trabalhador da fila). Pesados (só no `.venv-audio`): `decodificar`, `separar` (só os stems pedidos, trechos com transição, reserva por falta de memória, cache atômico), `transcricao` (`analisar` → `gerar`), `linha`, `ritmo`, `partitura`, `conferencia`; `bs_roformer/` é a rede vendorizada (MIT) |
| `testes/` | `unittest`; as saídas reais dos motores ficam em `testes/dados/`, fora do repositório (ver Testes) |

## Testes

```
.venv/bin/python -m unittest discover -s testes -v
.venv-audio/bin/python -m unittest discover -s testes -t . -p 'test_audio*'     # testes que precisam do ambiente de áudio
CENTRAL_PY_AUDIO=$PWD/.venv-audio/bin/python .venv/bin/python -m unittest testes.test_servidor_audio   # ponta a ponta API → fila → trabalhador
```

As referências em `testes/dados/` são leituras reais de uma partitura protegida por direitos autorais (uma foto de celular, as leituras do homr e do Audiveris e a transcrição revisada) e não vão para o repositório. Sem elas, os testes que as usam são pulados; os demais rodam normalmente.

Cobrem: pausas longas nos formatos do homr e do Audiveris; ligaduras de valor com acidente; correção dos trechos de pausa, inclusive dividida em grupos com fórmula de compasso (com os números certos, o resultado do homr bate 33/33 compassos com notas com a transcrição revisada); conferência igual à de referência; publicação sem sobrescrever (inclusive em sistema de arquivos sem links); cancelamento que encerra processos-netos; biblioteca com edição concorrente; servidor (ficha, `Host`, cabeçalho, caminhos com `../`); fila com trabalhador falso; .zip; pacote de revisão quando o Audiveris falha; limite de pixels do Audiveris. No modo de áudio: a transcrição da faixa do piloto (trechos, notas, andamento e tom iguais aos do piloto avaliado), a notação por instrumento (transposição, armadura, clave), o trabalhador com o cache de stems, a separação com um modelo falso (memória da GPU insuficiente → trechos menores → processador), a checagem do código vendorizado, o servidor e a fila com um trabalhador falso, o download por link com um yt-dlp falso (inclusive cancelar no meio) e o instalador (rodas, modelos e Node.js, sem rede).

## Manual em PDF

```
.venv/bin/python ferramentas/gerar_manual.py     # MANUAL.md → ../MANUAL.pdf
```

## Requisitos do modo de áudio

Para mudar uma versão, edite o `requisitos-audio.in` e gere de novo o `requisitos-audio.txt` (as restrições mantêm as outras versões como estão no ambiente instalado):

```
.venv/bin/python ferramentas/requisitos_audio.py --restricoes <(.venv/bin/uv pip freeze --python .venv-audio/bin/python)
```
