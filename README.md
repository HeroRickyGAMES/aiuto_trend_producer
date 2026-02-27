# IA Video Creator — Ciência, Tecnologia & Astronomia

Pipeline 100% local para criar vídeos de divulgação científica automaticamente.
Sem GPU obrigatória — funciona inteiramente na CPU.

```
TREND → ROTEIRO → NARRAÇÃO → MÍDIA → VÍDEO → EXPORT
```

---

## Índice

- [O que faz](#o-que-faz)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Instalação — Linux (Ubuntu/Debian)](#instalação--linux-ubuntudebian)
- [Instalação — CachyOS / Arch Linux](#instalação--cachyos--arch-linux)
- [Instalação — Windows](#instalação--windows)
- [Instalação — WSL (Windows Subsystem for Linux)](#instalação--wsl-windows-subsystem-for-linux)
- [Configuração](#configuração)
- [Clonagem de voz](#clonagem-de-voz)
- [Uso](#uso)
  - [Modo interativo](#modo-interativo-padrão)
  - [Modo automático `-a`](#modo-automático----a-batch-sem-interação)
  - [Referência de flags](#referência-de-flags)
- [Fontes de trends](#fontes-de-trends)
- [Modelos TTS](#modelos-tts)
- [Skills Claude Code](#skills-claude-code)
- [Solução de problemas](#solução-de-problemas)

---

## O que faz

| Passo | Módulo | O que acontece |
|-------|--------|----------------|
| 1 | `trend_hunter.py` | Busca tópicos em alta (Google Trends + Hacker News + NASA RSS) |
| 2 | `script_writer.py` | Gera roteiro com Ollama (IA local) |
| 3 | `media_fetcher.py` | Baixa imagens e vídeos do Pexels por cena |
| 4 | `tts_narrator.py` | Narra o roteiro com Coqui XTTS v2 (suporta clonagem de voz) |
| 5 | `video_editor.py` | Monta o vídeo com moviepy (Ken Burns, transições, mixagem) |
| 6 | `thumb_generator.py` + `metadata_gen.py` | Gera thumbnail e metadados prontos para o YouTube |

---

## Estrutura do projeto

```
ia_video_creator/
├── main.py                     # Orquestrador — executa os 6 passos
├── config.yaml                 # Suas configurações e chaves de API (não vai pro git)
├── config.yaml.exemplo         # Template — copie e edite
├── requirements.txt
├── modules/
│   ├── trend_hunter.py         # Google Trends + Hacker News + NASA RSS
│   ├── script_writer.py        # Roteiro via Ollama
│   ├── tts_narrator.py         # Narração XTTS v2 com clonagem de voz
│   ├── media_fetcher.py        # Imagens e vídeos do Pexels
│   ├── video_editor.py         # Montagem com moviepy
│   ├── thumb_generator.py      # Thumbnail 1280×720
│   └── metadata_gen.py         # Título, tags, descrição para YouTube
├── assets/
│   ├── voices/                 # Coloque aqui seu minha_voz.wav
│   └── media_cache/            # Cache automático do Pexels (ignorado no git)
├── export/                     # Vídeos finais gerados (ignorado no git)
└── temp/                       # Arquivos temporários do pipeline (ignorado no git)
```

---

## Instalação — Linux (Ubuntu/Debian)

Testado no Ubuntu 22.04 / 24.04 e derivados.

### 1. Dependências do sistema

```bash
sudo apt update
sudo apt install -y ffmpeg python3 python3-pip python3-venv git
```

### 2. Instalar Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh

# Baixar o modelo de linguagem (escolha um):
ollama pull gemma2        # recomendado — bom PT-BR, leve
ollama pull llama3.2
ollama pull mistral
```

### 3. Clonar e configurar o projeto

```bash
git clone https://github.com/seu-usuario/ia_video_creator.git
cd ia_video_creator

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

> O primeiro `pip install` demora — PyTorch (~700 MB) e Coqui TTS são pesados.

> **Compatibilidade torchaudio:** versões >= 2.5 (incluindo a 2.10 atual) tentam usar `torchcodec` como backend de áudio, que não é instalado por padrão. O projeto já contém um patch automático em `tts_narrator.py` que força o backend `soundfile`. Nenhuma ação necessária.

### 4. Configurar

```bash
cp config.yaml.exemplo config.yaml
nano config.yaml   # adicione sua chave Pexels e ajuste o modelo
```

---

## Instalação — CachyOS / Arch Linux

CachyOS é Arch-based com repositórios próprios e chaotic-AUR. Use `pacman` + `yay`.

### 1. Dependências do sistema

```bash
sudo pacman -S --needed ffmpeg python python-pip git base-devel

# yay (AUR helper) — pule se já tiver
git clone https://aur.archlinux.org/yay.git /tmp/yay
cd /tmp/yay && makepkg -si && cd -
```

### 2. Instalar Ollama

```bash
# Via AUR
yay -S ollama

# Iniciar o serviço
sudo systemctl enable --now ollama

# Baixar modelo
ollama pull gemma2
```

> No CachyOS com kernel cachyos-bore, o Ollama aproveita bem os schedulers de baixa latência.

### 3. Clonar e configurar o projeto

```bash
git clone https://github.com/seu-usuario/ia_video_creator.git
cd ia_video_creator

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

### 4. Nota sobre PyTorch no Arch

O `pip install torch` instala a versão CPU por padrão. Se tiver GPU AMD e ROCm estável:

```bash
# Apenas se souber o que está fazendo — ROCm no Arch pode ser instável
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.1
```

Para RX580 e similares, **CPU é mais estável** — mantenha o padrão.

> **Compatibilidade torchaudio:** mesma nota do Linux — patch automático já resolve, sem ação necessária.

### 5. Configurar

```bash
cp config.yaml.exemplo config.yaml
nano config.yaml
```

---

## Instalação — Windows

Testado no Windows 10 21H2+ e Windows 11.

### 1. Instalar Python

Baixe o instalador em https://www.python.org/downloads/
**Marque "Add Python to PATH"** durante a instalação.

Ou via winget:
```powershell
winget install Python.Python.3.12
```

### 2. Instalar FFmpeg

**Opção A — winget (recomendado):**
```powershell
winget install Gyan.FFmpeg
```

**Opção B — manual:**
1. Baixe em https://ffmpeg.org/download.html (build "essentials")
2. Extraia para `C:\ffmpeg`
3. Adicione `C:\ffmpeg\bin` ao `PATH` do sistema

Verifique:
```powershell
ffmpeg -version
```

### 3. Instalar Ollama

Baixe o instalador `.exe` em https://ollama.com/download/windows e execute.

Após instalar, em um terminal:
```powershell
ollama pull gemma2
```

### 4. Clonar e configurar o projeto

```powershell
git clone https://github.com/seu-usuario/ia_video_creator.git
cd ia_video_creator

python -m venv .venv
.venv\Scripts\activate        # PowerShell
# ou: .venv\Scripts\activate.bat  (CMD)

pip install -r requirements.txt
```

### 5. Configurar

```powershell
copy config.yaml.exemplo config.yaml
notepad config.yaml
```

### 6. Executar

```powershell
.venv\Scripts\activate
python main.py
```

> **Nota:** o Coqui TTS no Windows faz download do modelo XTTS v2 (~1,8 GB) na primeira execução. Pode demorar dependendo da conexão.

---

## Instalação — WSL (Windows Subsystem for Linux)

O WSL2 é a forma mais confortável de rodar no Windows — desempenho próximo ao Linux nativo.

### 1. Instalar WSL2

Em um PowerShell **como Administrador**:
```powershell
wsl --install          # instala Ubuntu por padrão
wsl --set-default-version 2
```

Reinicie o computador, abra o Ubuntu e crie usuário/senha.

### 2. Seguir a instalação Linux

Dentro do terminal Ubuntu no WSL, siga exatamente os passos da seção [Linux (Ubuntu/Debian)](#instalação--linux-ubuntudebian).

### 3. Instalar Ollama no WSL

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &   # inicia em background dentro do WSL
ollama pull gemma2
```

> O Ollama para Windows NÃO é acessível de dentro do WSL por padrão. Instale separadamente dentro do WSL.

### 4. Acessar os vídeos exportados pelo Windows Explorer

Os arquivos do WSL ficam em:
```
\\wsl$\Ubuntu\home\SEU_USUARIO\ia_video_creator\export\
```

Você pode abrir essa pasta no Explorer e copiar os vídeos normalmente.

### 5. Dica de desempenho no WSL2

Crie ou edite `%USERPROFILE%\.wslconfig` no Windows:
```ini
[wsl2]
memory=16GB       # ajuste para metade da sua RAM
processors=6      # núcleos disponíveis para o WSL
swap=4GB
```

Reinicie o WSL:
```powershell
wsl --shutdown
```

---

## Configuração

Copie o exemplo e edite:
```bash
cp config.yaml.exemplo config.yaml
```

### Chaves de API necessárias

| API | Link | Custo | Onde colocar |
|-----|------|-------|--------------|
| **Pexels** | https://www.pexels.com/api/ | Gratuito | `media.pexels_api_key` |

> Hacker News e NASA RSS não exigem chave.

### Opções mais importantes do `config.yaml`

```yaml
llm:
  model: gemma2           # modelo Ollama instalado localmente
  temperature: 0.7        # criatividade do roteiro (0.0–1.0)

tts:
  model: tts_models/multilingual/multi-dataset/xtts_v2
  language: pt            # código de idioma para XTTS v2
  speed: 1.0              # 1.0 = natural — não ajuste para naturalidade; use temperature
  voice_sample: assets/voices/minha_voz.wav   # clonagem de voz (opcional)

  # Naturalidade da fala — ajuste fino de prosódia
  generation:
    temperature: 0.75     # 0.6 = robótico | 0.75 = natural (padrão) | 0.9 = expressivo
    top_k: 50
    top_p: 0.85
    repetition_penalty: 1.1

video:
  resolution: [1920, 1080]
  fps: 30
  background_music_volume: 0.08   # 0 = sem música, 0.15 = alta

script:
  duration_target: 300    # duração alvo em segundos
```

---

## Clonagem de voz

O XTTS v2 pode narrar com a **sua voz** a partir de uma gravação de referência.

### Requisitos da gravação

- Duração: **mínimo 5 segundos** — arquivos longos também funcionam; o XTTS v2 usa apenas os primeiros 30s (`gpt_cond_len=30`) e ignora o restante. Mais áudio limpo = melhor captura de timbre
- Formato: WAV, MP3 ou FLAC
- Canais: **mono** (1 canal) — estéreo funciona mas mono é mais estável
- Sample rate: **22050 Hz** recomendado (44100 Hz também aceito)
- Conteúdo: fale qualquer coisa naturalmente, em português — não precisa ser o texto do vídeo
- Qualidade: microfone de headset já é suficiente; evite música de fundo ou eco
- Localização: o arquivo **deve estar em `assets/voices/minha_voz.wav`** — qualquer outro caminho exige atualizar `voice_sample` no `config.yaml`

### Dica de gravação

Para melhor resultado, grave lendo em voz natural (não forçada) algo como:
> "A ciência é a linguagem do universo. Cada descoberta nos aproxima da verdade sobre nossa existência no cosmos e nos lembra que somos feitos de poeira de estrelas."

### Como adicionar

```bash
# Opção 1 — gravar pelo terminal (necessita sox)
# Linux/WSL:
sudo apt install sox
rec -r 22050 -c 1 assets/voices/minha_voz.wav trim 0 10

# CachyOS/Arch:
sudo pacman -S sox
rec -r 22050 -c 1 assets/voices/minha_voz.wav trim 0 10

# Opção 2 — converter uma gravação existente
ffmpeg -i gravacao.mp3 -ar 22050 -ac 1 assets/voices/minha_voz.wav
```

O pipeline detecta automaticamente se o arquivo existe. Sem ele, usa a voz padrão do modelo.

---

## Uso

### Modo interativo (padrão)

```bash
python3 main.py       # Linux / WSL / CachyOS
python main.py        # Windows
```

O sistema:
1. Busca trends (Google Trends + Hacker News + NASA RSS)
2. Exibe lista para você escolher (ou digitar manualmente)
3. Gera roteiro com IA e mostra para aprovação
4. Sintetiza a narração com clonagem de voz
5. Busca imagens e vídeos no Pexels
6. Monta o vídeo com transições e Ken Burns
7. Gera thumbnail 1280×720 + metadados para YouTube

---

### Modo automático — `-a` (batch sem interação)

Processa **todas as trends de uma vez**, sem precisar acompanhar.
Ideal para deixar rodando em segundo plano e pegar os vídeos prontos depois.

```bash
python3 main.py -a        # Linux / WSL / CachyOS
python main.py -a         # Windows
```

**O que acontece:**
1. Busca todas as trends disponíveis nas 3 fontes
2. Exibe a lista completa com fontes e scores
3. Pede confirmação **uma única vez**: `"Iniciar processamento de N vídeos? [s/n]"`
4. Processa cada trend automaticamente, uma por uma
5. Se uma falhar, loga o erro e continua para a próxima
6. Ao final exibe um resumo com status, pasta e tempo de cada vídeo

**Estrutura de saída:**

Cada trend gera uma subpasta própria dentro de `export/`:

```
export/
├── inteligencia_artificial_ia/
│   ├── video_20260225_161200.mp4
│   ├── video_20260225_161200_thumb.jpg
│   ├── video_20260225_161200_titulo.txt
│   ├── video_20260225_161200_descricao.txt
│   ├── video_20260225_161200_tags.txt
│   └── video_20260225_161200_metadata.json
├── space_astronomy/
│   └── ...
└── quantum_computing/
    └── ...
```

**Exemplo de resumo ao final:**

```
══════════════════════════════════════════════════════════════
  MODO AUTO — RESUMO FINAL
══════════════════════════════════════════════════════════════
  [✓] Inteligência Artificial Ia
        Pasta : ./export/inteligencia_artificial_ia/
        Tempo : 0:12:43
  [✓] Space Astronomy
        Pasta : ./export/space_astronomy/
        Tempo : 0:09:17
  [✗] O Que E Tecnologia
        ERRO: Ollama connection refused
        Tempo : 0:00:03
══════════════════════════════════════════════════════════════
  Concluídos : 2/3
  Com erro   : 1
  Tempo total: 0:22:05
══════════════════════════════════════════════════════════════
```

---

### Pular a busca de trends (tema direto)

```bash
python3 main.py --tema "Fusão Nuclear"
python3 main.py --tema "Buracos Negros Supermassivos"
python3 main.py --tema "CRISPR e Edição Genética"
```

### Usar configuração alternativa (multi-canal)

```bash
python3 main.py --config canal_astronomia.yaml
python3 main.py --config canal_medicina.yaml
```

### Listar modelos TTS disponíveis em PT

```bash
python3 main.py --listar-modelos-tts
```

### Referência de flags

| Flag | Atalho | Descrição |
|------|--------|-----------|
| `--auto` | `-a` | Processa todas as trends automaticamente |
| `--tema "X"` | — | Usa o tema X diretamente, sem buscar trends |
| `--config X.yaml` | — | Usa arquivo de configuração alternativo |
| `--listar-modelos-tts` | — | Lista modelos TTS em PT disponíveis e sai |

---

## Fontes de trends

| Fonte | Tipo | Conteúdo |
|-------|------|----------|
| **Google Trends** | API (pytrends) | Buscas em alta no Brasil por categoria |
| **Hacker News** | API Algolia (sem auth) | Tech, IA, computação, ciência |
| **NASA Breaking News** | RSS público | Astronomia, exploração espacial |
| **SpaceFlightNow** | RSS público | Lançamentos, missões, satélites |

Quando todas as APIs falharem, o sistema oferece entrada manual do tema.

---

## Modelos TTS

| Modelo | Qualidade | Velocidade CPU | Clonagem de voz |
|--------|-----------|----------------|-----------------|
| `tts_models/pt/cv/vits` | Boa | Rápido (~5s/cena) | Não |
| `tts_models/multilingual/multi-dataset/xtts_v2` | Excelente | Lento (~2–5 min/cena) | **Sim** |

O XTTS v2 (~1,8 GB) é baixado automaticamente na primeira execução.

### Como a naturalidade da voz funciona

O pipeline aplica várias técnicas para soar humano:

| Técnica | Onde | Efeito |
|---------|------|--------|
| `temperature=0.75` + `do_sample=True` | Geração XTTS | Variação rítmica e prosódica natural |
| `repetition_penalty=1.1` | Geração XTTS | Elimina loops e chiados repetitivos |
| Divisão por sentença completa | `tts_narrator.py` | Cada unidade de fala é coerente |
| Pausas por pontuação | `tts_narrator.py` | `.` = 380ms, `!` = 320ms, `,` = 90ms |
| Strip de silêncio | `tts_narrator.py` | Remove silêncios extras do XTTS entre chunks |
| High-pass 80 Hz (scipy) | `tts_narrator.py` | Remove rumble e DC offset |
| Noise gate | `tts_narrator.py` | Silencia ruído entre frases |
| Normalização para −16 dBFS | `tts_narrator.py` | Volume consistente (padrão YouTube/podcast) |
| Números por extenso (num2words) | Pré-processamento | "5 planetas" → "cinco planetas" |

---

## Saída do pipeline

```
export/
├── video_YYYYMMDD_HHMMSS.mp4                    # Vídeo final 1080p
├── video_YYYYMMDD_HHMMSS_thumb.jpg              # Thumbnail 1280×720
├── video_YYYYMMDD_HHMMSS_titulo.txt             # Título para YouTube
├── video_YYYYMMDD_HHMMSS_descricao.txt          # Descrição com hashtags
├── video_YYYYMMDD_HHMMSS_tags.txt               # Tags separadas por vírgula
└── video_YYYYMMDD_HHMMSS_metadata.json          # Tudo junto em JSON
```

---

## Solução de problemas

### `ImportError: TorchCodec is required for load_with_torchcodec`
`torchaudio >= 2.5` trocou o backend padrão para `torchcodec`, que não vem instalado. Já corrigido via monkey-patch em `tts_narrator.py` — substitui `torchaudio.load` por implementação `soundfile` automaticamente. Nenhuma ação necessária.

### Áudio com "aaaa" em loop / narração incoerente
Causado pelo `transformers >= 4.46` que pré-aloca um `DynamicCache` vazio antes do primeiro forward pass do XTTS. O modelo recebe só o token inicial sem contexto e gera lixo. Já corrigido com monkey-patch em `tts_narrator.py`. Confirme no log:
```
[TTSNarrator] Patch DynamicCache aplicado (fix transformers>=4.46)
```
Se não aparecer, verifique se `transformers >= 4.57.0` está instalado:
```bash
.venv/bin/python -c "import transformers; print(transformers.__version__)"
```

### `TypeError: Cannot create a consistent method resolution order (MRO)`
Versão de `transformers` entre 4.35 e 4.56 onde `GPT2PreTrainedModel` herdava `GenerationMixin`, conflitando com o `GPT2InferenceModel` do XTTS. Solução:
```bash
pip install "transformers>=4.57.0"
```

### Tom robótico / fala monótona / staccato
A naturalidade vem dos parâmetros de geração, não de `speed`. Verifique o `config.yaml`:
```yaml
tts:
  speed: 1.0              # mantenha em 1.0
  generation:
    temperature: 0.75     # aumente para 0.80–0.85 se ainda soar robótico
    repetition_penalty: 1.1
```

### Chiados ou hissing no áudio
Pode ser ruído de fundo no arquivo `minha_voz.wav` ou `repetition_penalty` muito baixo. Tente:
```yaml
generation:
  repetition_penalty: 1.15
```
E verifique se `scipy` está instalado (necessário para o filtro high-pass e noise gate):
```bash
pip install scipy>=1.10.0
```

### `Retry.__init__() got an unexpected keyword argument 'method_whitelist'`
Incompatibilidade entre `pytrends` e `urllib3 >= 2.0`. Já corrigido — não passe `retries` ao `TrendReq`.

### Google Trends retorna 429
O Google limita requisições muito rápidas. O pipeline já adiciona delay progressivo (3–5s entre categorias). Se persistir, aguarde alguns minutos e tente novamente, ou use `--tema`.

### Reddit 403 Blocked
Reddit bloqueou a API pública em 2023. **Removido do projeto** — substituído por Hacker News e NASA RSS.

### Voz feminina no vídeo (Daisy Studious) / sem clonagem
O XTTS v2 está rodando sem clonagem de voz. "Daisy Studious" é uma falante **inglesa feminina** — o resultado em português fica com sotaque e prosódia ruins.

Causas comuns:
- Arquivo em lugar errado — o config espera `assets/voices/minha_voz.wav`
- Arquivo muito curto — mínimo 5 segundos; abaixo disso o modelo não captura timbre suficiente
- Arquivo não existe ainda — grave sua voz (veja seção [Clonagem de voz](#clonagem-de-voz))

Confirme que a clonagem está ativa procurando no log:
```
[TTSNarrator] Modo clonagem ATIVO: .../assets/voices/minha_voz.wav
```

### `TTS` não instala / erro de compilação
Certifique-se de ter as ferramentas de build:
```bash
# Ubuntu/Debian/WSL
sudo apt install build-essential python3-dev

# CachyOS/Arch
sudo pacman -S base-devel

# Windows
pip install --upgrade setuptools wheel
```

### Vídeo exportado sem áudio
Verifique se o `ffmpeg` está instalado e acessível no PATH:
```bash
ffmpeg -version
```

### WSL — `ollama: command not found`
O Ollama instalado no Windows não é acessível dentro do WSL. Instale-o separadamente dentro do WSL:
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### CachyOS — PyTorch lento mesmo na CPU
Verifique se `torch` está instalado sem CUDA desnecessário:
```bash
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"
# deve imprimir: False
```

---

## Skills Claude Code

Se você usa o Claude Code (CLI) para desenvolver este projeto, há skills disponíveis em `.claude/skills/`:

| Skill | Comando | O que faz |
|-------|---------|-----------|
| `make-video` | `/make-video` | Guia para rodar o pipeline completo, verifica ambiente e Ollama |
| `debug-tts` | `/debug-tts` | Diagnóstico completo de problemas de áudio — versões, qualidade do wav, teste de síntese |
| `ajustar-voz` | `/ajustar-voz` | Processa e configura o arquivo de referência para clonagem de voz |

As skills são locais ao projeto (`.claude/skills/`) e ficam disponíveis automaticamente ao abrir o projeto no Claude Code.

---

## APIs necessárias (resumo)

| API | Obrigatória | Gratuita | Link |
|-----|-------------|----------|------|
| **Pexels** | Sim | Sim | https://www.pexels.com/api/ |
| **Ollama** | Sim | Sim (local) | https://ollama.com |
| **Hacker News** | Não | Sim | automático |
| **NASA RSS** | Não | Sim | automático |
| **Google Trends** | Não | Sim | automático |
