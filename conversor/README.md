# Conversor de partitura (foto/PDF → MuseScore)

Transforma fotos do celular (HEIC, JPG, PNG) ou PDF de partitura em um arquivo `.mscz` para editar no MuseScore.
O reconhecimento roda no seu computador, com um de dois programas livres:

- [homr](https://github.com/liebharc/homr) (padrão), feito para fotos de celular;
- [Audiveris](https://github.com/Audiveris/audiveris).

O resultado é um **rascunho para revisar**, não uma cópia perfeita. Junto com ele sai um relatório que aponta onde conferir.

## Instalação (uma vez)

```bash
cd image-to-music/conversor
./instalar.sh
```

Tudo fica dentro desta pasta, cerca de 800 MB: os dois motores, um ambiente Python e os dados de OCR. Na primeira conversão o homr baixa os modelos dele.
O instalador precisa destes programas no sistema: MuseScore 4 (`mscore`), ImageMagick (`magick`), `pdftoppm` (poppler), `curl` e `ar` (binutils).

## Uso

```bash
# fotos, na ordem das páginas
./converter pagina1.heic pagina2.heic -o "Minha musica.mscz"

# completo: título, créditos, nome da parte e PDF para comparar
./converter pagina1.heic pagina2.heic -o "Hino.mscz" \
  --titulo "My Savior and My Son" --compositor "Joel Lindsey / arr. Bradley Knight" \
  --instrumento "Trombone 3 / Tuba" --pdf

# outro motor e guias de altura para clave de fá
./converter partitura.pdf -o partitura.mscz --motor audiveris --guias fa
```

| Opção | Para que serve |
|---|---|
| `-o` | arquivo `.mscz` de saída |
| `--motor homr` ou `--motor audiveris` | programa de reconhecimento (padrão: `homr`) |
| `--titulo`, `--compositor`, `--instrumento` | textos do cabeçalho e nome da parte |
| `--pdf` | também gera um PDF do resultado, para comparar com o original |
| `--guias fa` ou `--guias sol` | gera imagens de cada sistema com o nome das notas desenhado nas linhas suplementares |
| `--manter` | mantém a pasta temporária (imagens preparadas e logs) |

Uma conversão de duas páginas leva cerca de 40 s com o homr e cerca de 1 min com o Audiveris.

## Qual motor usar

Teste com *My Savior and My Son* (Trombone 3/Tuba, 2 fotos de celular, 165 compassos, 33 deles com notas):

| | homr | Audiveris |
|---|---|---|
| Compassos com notas certos | **32 de 33** | cerca de 21 de 33 |
| Semibreves com linhas suplementares | acertou | perdeu quase todas |
| Pausas de vários compassos com dois dígitos | erradas (leu 11, 19, 20 como 8) | erradas |
| Ligaduras de valor | vêm como ligaduras de expressão | sim |
| Dinâmicas, textos, fermatas | não | sim (textos com erros de OCR) |
| Acentos | parte | sim |

Use o **homr** para fotos; ele erra menos as notas. O **Audiveris** vale para scans limpos ou quando dinâmicas e textos importam mais. Dá para rodar os dois e comparar.

## O que o conversor faz

1. Lê as páginas: converte HEIC e corrige a rotação da foto.
2. Reconhece cada página. Com o Audiveris, antes recorta o fundo escuro, amplia a imagem até a distância entre as linhas da pauta ficar em cerca de 32 px e junta as páginas num único PDF.
3. Junta as páginas numa partitura só. Também garante que cada pausa de N compassos tenha N compassos reais (o homr grava só um), para a numeração e a reprodução ficarem certas.
4. Limpa o cabeçalho: os textos lidos pelo OCR saem desalinhados, então vão para o relatório.
5. Confere os compassos e converte para `.mscz` com o MuseScore.

## Como revisar (o passo que garante o resultado)

Abra a partitura original e o `.mscz` lado a lado e use o arquivo `*-conferencia.txt`. Ele aponta quatro coisas:

- **Total de compassos**, para comparar com o último número impresso. No teste deu 93 em vez de 165, por causa das pausas longas.
- **Pausas de vários compassos.** Corrija o número no MuseScore inserindo compassos vazios; a pausa longa é redesenhada sozinha.
- **Compassos com duração errada**, onde alguma figura foi mal reconhecida.
- **Compassos só com pausa**, onde podem estar notas que não foram reconhecidas.

Depois, acrescente o que o motor não traz: dinâmicas, *rit.*, *a tempo*, fermatas e acentos. Troque as ligaduras de expressão por ligaduras de valor onde for o caso (tecla `+`). Nos compassos ligados, confira os acidentes: o Dó♮ do c. 16 ligado até o c. 19 saiu como Dó♯ no c. 19.

Notas graves com várias linhas suplementares são fáceis de errar no olho. A opção `--guias` desenha o nome de cada linha e espaço (Mi2, Dó2, Lá1…) sobre a foto.

## Para melhorar o resultado

- **Capture bem.** Scanner de mesa (Simple Scan, 300–400 dpi, tons de cinza) ou o modo documento de um app de digitalização (Google Drive, Microsoft Lens). Papel plano, luz difusa, sem sombra, uma página por imagem.
- **Para peças importantes**, compare com o Soundslice, que roda no navegador, aceita HEIC e exporta MusicXML (2 páginas grátis por mês).
- **Revisão assistida pelo Claude:** peça para conferir o rascunho contra as fotos usando as imagens de `--guias`. Foi assim que a versão final de *My Savior and My Son* foi corrigida.
