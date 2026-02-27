# ajustar-voz

Ajuda a gravar, processar e configurar o áudio de referência para clonagem de voz no XTTS v2.

## Uso
`/ajustar-voz [caminho do arquivo de áudio]`

## Requisitos do áudio de referência ideal

| Parâmetro | Valor ideal |
|---|---|
| Duração | mínimo 5s (arquivos longos OK — XTTS usa até 30s) |
| Canais | Mono (1) |
| Sample rate | 22050 Hz |
| Nível (dBFS) | Entre -18 e -10 dBFS |
| Conteúdo | Fala contínua, sem música ou ruído de fundo |
| Formato | WAV (preferido), MP3 ou FLAC |

## Processar um arquivo existente

Se o usuário tem um arquivo de áudio, processe-o com:

```python
from pydub import AudioSegment
from pydub.effects import normalize

# Carrega o arquivo
audio = AudioSegment.from_file("caminho/do/arquivo.wav")

# Converte para mono se necessário
if audio.channels > 1:
    audio = audio.set_channels(1)

# Ajusta sample rate
audio = audio.set_frame_rate(22050)

# Recorta para 13s (pega os melhores 13s do começo)
audio = audio[:13000]

# Normaliza volume
audio = normalize(audio)

# Salva
audio.export("assets/voices/minha_voz.wav", format="wav")
print(f"Salvo! Duração: {len(audio)/1000:.1f}s | dBFS: {audio.dBFS:.1f}")
```

## Verificar qualidade do áudio atual

```bash
.venv/bin/python -c "
from pydub import AudioSegment
import numpy as np

a = AudioSegment.from_wav('assets/voices/minha_voz.wav')
samples = np.array(a.get_array_of_samples(), dtype=np.float32) / 32768.0

print(f'Duração:     {len(a)/1000:.1f}s')
print(f'Canais:      {a.channels}')
print(f'Sample rate: {a.frame_rate} Hz')
print(f'dBFS médio:  {a.dBFS:.1f}')
print(f'Variância:   {np.var(samples):.4f}  (>0.01 = sinal presente, <0.001 = muito silencioso)')

# Energia por segundo
for i in range(0, min(len(a), 13000), 1000):
    seg = a[i:i+1000]
    print(f'  {i//1000}s: {seg.dBFS:.1f} dBFS')
"
```

## Extrair clipe de um arquivo longo

Se tiver um arquivo de áudio longo (ex: gravação de vídeo):

```python
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

audio = AudioSegment.from_file("arquivo_longo.wav")
audio = audio.set_channels(1).set_frame_rate(22050)

# Encontra partes com fala
chunks = detect_nonsilent(audio, min_silence_len=500, silence_thresh=-40)
if chunks:
    inicio, fim = chunks[0]  # Primeiro trecho de fala
    clipe = audio[inicio:min(inicio + 13000, fim)]
    clipe = clipe.normalize()
    clipe.export("assets/voices/minha_voz.wav", format="wav")
    print(f"Clipe extraído: {len(clipe)/1000:.1f}s")
```

## Onde o arquivo deve estar
```
ia_video_creator/
└── assets/
    └── voices/
        └── minha_voz.wav  ← aqui
```

Configuração em `config.yaml`:
```yaml
tts:
  voice_sample: assets/voices/minha_voz.wav
```

## Dica: gravação ideal
Para clonar bem, grave **lendo em voz natural** (não forçada), um trecho como:
> "A ciência é a linguagem do universo. Cada descoberta nos aproxima da verdade sobre nossa existência no cosmos."

Grave em ambiente silencioso, sem eco. Microfone do celular funciona se não houver ruído.
