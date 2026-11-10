# Central de Partituras

Transforma fotos de celular (ou PDFs) de partituras em arquivos do **MuseScore** (`.mscz`). Você importa as fotos, agrupa e ordena as páginas de cada música, converte em fila com o **homr** ou o **Audiveris** e confere o resultado num relatório que aponta onde revisar. Tudo roda no seu computador.

![Tela principal da Central de Partituras](conversor/partituras/static/manual/tela-musicas.jpg)

## O que faz

- **Muitas músicas, várias fotos cada**: importa tudo de uma vez e sugere os grupos pela hora em que as fotos foram tiradas; as páginas se reordenam arrastando.
- **Conversão em fila**, com progresso e cancelamento. Nunca sobrescreve um arquivo existente: salva como "Nome (2)".
- **Correções automáticas**: ligaduras de valor (com o acidente que passa pela ligadura) e pausas longas, que você acerta em segundos digitando os números da partitura impressa.
- **Relatório** com mapa de compassos, alertas de duração errada e de nota provavelmente perdida, e checklist de revisão.
- **Transcrever um áudio**: separa o sax, o trompete ou o trombone de uma gravação (arquivo ou link), acha os trechos em que ele toca e escreve a parte já transposta para o instrumento, com escuta A/B (transcrição tocando sobre a gravação) para conferir.
- **Extras**: os dois motores lado a lado, pacote de revisão assistida pelo Claude e exportação de tudo em `.zip`.

## Requisitos

Linux com GNOME (feito e testado no Fedora 44), Python 3, MuseScore 4 (`mscore`), ImageMagick (`magick`), poppler (`pdftoppm`), binutils (`ar`), `curl`, Google Chrome ou Chromium e zenity; para o modo de áudio, também `ffmpeg` e, para importar por link, Node.js.

## Instalação

```bash
git clone https://github.com/felipealvss/central-de-partituras.git
cd central-de-partituras
conversor/instalar.sh
```

O instalador cria o ambiente Python (homr, Flask, waitress…), baixa o Audiveris 5.11 e os dados de OCR, tudo dentro de `conversor/`, e oferece um atalho no menu de aplicativos.

Para transcrever áudio (opcional; ocupa cerca de 7,5 GB e precisa de uns 12 GB livres durante a instalação): `conversor/instalar.sh --audio`. Ele cria um ambiente Python 3.12 com PyTorch (usa a placa de vídeo NVIDIA, se houver), com as versões fixadas e o hash de cada pacote em `conversor/requisitos-audio.txt`, e baixa o modelo de separação "MVSep Mega 53 Stems" (BS-RoFormer) e o Beat This!, conferindo o SHA-256 de cada um. Precisa do `ffmpeg`; o `aria2c`, se instalado, acelera os downloads grandes. Para atualizar só o yt-dlp (importar por link): `conversor/instalar.sh --atualizar-yt-dlp`.

## Uso

Abra **Central de Partituras** no menu de aplicativos ou rode `./abrir-conversor.sh`. O passo a passo está no [manual](MANUAL.md), que também aparece na aba *Ajuda* do programa.

Suas fotos, músicas e partituras ficam nas pastas `entrada/`, `musicas/`, `partituras/` e `exportados/`, criadas no primeiro uso. Elas não entram no repositório.

## Para quem for mexer no código

Estrutura, linha de comando e testes: [conversor/README.md](conversor/README.md).

## Licença

Código sob a [licença MIT](LICENSE). O homr e o Audiveris, que o instalador baixa, são programas separados, com licença própria (AGPL-3.0). A rede do modelo de separação em `conversor/partituras/audio/bs_roformer/` é código de terceiros sob MIT (ZFTurbo e lucidrains; ver o LICENSE da pasta); os pesos dos modelos são baixados pelo instalador e não fazem parte do repositório.
