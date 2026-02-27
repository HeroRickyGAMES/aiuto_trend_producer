# IA Video Creator — Ciência & Tecnologia

Pipeline completo em Python (CPU) para criação automática de vídeos de ciência e tecnologia para YouTube.

Inspirado na engine do [ia_dubla_animes](https://github.com/HeroRickyGAMES/ia_dubla_animes).

---

## Como funciona

```
Google Trends + Reddit
       ↓
   Você escolhe a trend
       ↓
   Ollama gera o roteiro
       ↓
   Você revisa e aprova
       ↓
   Pexels → imagens e vídeos
       ↓
   Coqui TTS → narração
       ↓
   moviepy → monta o vídeo
       ↓
   Pillow → thumbnail
       ↓
   export/ → vídeo + thumb + título + descrição + tags
```

---

## Instalação

### 1. Dependências do sistema

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg python3-pip -y

# Windows: baixe o ffmpeg em https://ffmpeg.org e adicione ao PATH
```

### 2. Python

```bash
pip install -r requirements.txt
```

> ⚠️ Para CPU only (sem CUDA), instale o PyTorch CPU:
> ```bash
> pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
> pip install -r requirements.txt
> ```

### 3. Ollama (IA de roteiro local)

```bash
bash setup_ollama.sh
# Depois mantenha rodando em background:
ollama serve
```

### 4. APIs gratuitas necessárias

| Serviço | O que faz | Link |
|---------|-----------|------|
| **Pexels** | Imagens e vídeos | https://www.pexels.com/api/ |
| **Reddit** (opcional) | Trends adicionais | https://www.reddit.com/prefs/apps |

---

## Configuração

```bash
cp config.yaml.exemplo config.yaml
# Edite o config.yaml e preencha suas chaves de API
```

Campos obrigatórios no `config.yaml`:
```yaml
apis:
  pexels_api_key: "SUA_CHAVE_AQUI"

ollama:
  model: "llama3"   # ou mistral, gemma2, phi3
```

---

## Uso

### Modo completo (interativo)
```bash
python main.py
```

O sistema vai:
1. Buscar trends e exibir lista para você escolher
2. Gerar o roteiro e pedir sua aprovação
3. Baixar imagens/vídeos do Pexels
4. Narrar com TTS
5. Montar o vídeo
6. Salvar tudo em `export/`

### Modo com tema fixo (pula busca de trends)
```bash
python main.py --tema "Buracos Negros"
python main.py --tema "Inteligência Artificial em 2025"
```

### Config alternativo
```bash
python main.py --config outro_config.yaml
```

### Ver modelos TTS disponíveis em português
```bash
python main.py --listar-modelos-tts
```

---

## Estrutura do projeto

```
ia_video_creator/
├── main.py                    # Orquestrador principal
├── config.yaml                # Suas configurações (criar a partir do .exemplo)
├── config.yaml.exemplo        # Template de configuração
├── requirements.txt
├── setup_ollama.sh            # Instala Ollama + modelo
│
├── modules/
│   ├── trend_hunter.py        # Busca trends (Google Trends + Reddit)
│   ├── script_writer.py       # Gera roteiro via Ollama
│   ├── tts_narrator.py        # Síntese de voz Coqui TTS
│   ├── media_fetcher.py       # Baixa mídia do Pexels
│   ├── video_editor.py        # Monta o vídeo (moviepy)
│   ├── thumb_generator.py     # Cria thumbnail (Pillow)
│   └── metadata_gen.py        # Gera título/descrição/tags
│
├── assets/
│   ├── fonts/                 # Fontes (ex: Montserrat-Bold.ttf do Google Fonts)
│   ├── logo.png               # Seu logo (opcional)
│   ├── background_music.mp3   # Música ambiente (opcional, royalty-free)
│   └── media_cache/           # Cache de mídia baixada (auto)
│
└── export/                    # Saída final
    ├── video_YYYYMMDD_HHMMSS.mp4
    ├── video_YYYYMMDD_HHMMSS_thumb.jpg
    ├── video_YYYYMMDD_HHMMSS_titulo.txt
    ├── video_YYYYMMDD_HHMMSS_descricao.txt
    ├── video_YYYYMMDD_HHMMSS_tags.txt
    └── video_YYYYMMDD_HHMMSS_metadata.json
```

---

## Modelos TTS recomendados (português)

| Modelo | Qualidade | Velocidade |
|--------|-----------|------------|
| `tts_models/pt/cv/vits` | Boa | Rápido |
| `tts_models/multilingual/multi-dataset/xtts_v2` | Excelente | Mais lento |

---

## Dicas

- **Música de fundo**: Baixe no [Pixabay](https://pixabay.com/music/) (royalty-free) e salve em `assets/background_music.mp3`
- **Fonte**: Baixe [Montserrat Bold](https://fonts.google.com/specimen/Montserrat) e salve em `assets/fonts/Montserrat-Bold.ttf`
- **Tempo de processamento**: Um vídeo de 5 minutos leva ~15-30min em CPU dependendo do hardware
- **Cache**: Imagens baixadas ficam em `assets/media_cache/` e são reutilizadas automaticamente

---

Feito com 💙 por HeroRickyGAMES — baseado no ia_dubla_animes
