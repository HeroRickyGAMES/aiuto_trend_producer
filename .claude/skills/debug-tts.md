# debug-tts

Diagnostica e corrige problemas de qualidade de áudio/TTS no IA Video Creator.

## Uso
`/debug-tts`

## Diagnóstico passo a passo

### 1. Verifique versões críticas
```bash
.venv/bin/python -c "import transformers; print('transformers:', transformers.__version__)"
.venv/bin/python -c "import TTS; print('TTS:', TTS.__version__)"
.venv/bin/python -c "import torchaudio; print('torchaudio:', torchaudio.__version__)"
```
- `transformers` deve ser **>=4.57.0** (versões 4.35-4.56 têm MRO error)
- `TTS` deve ser **0.22.0**

### 2. Verifique o arquivo de voz
```bash
ls -lh assets/voices/minha_voz.wav
.venv/bin/python -c "
from pydub import AudioSegment
a = AudioSegment.from_wav('assets/voices/minha_voz.wav')
print(f'Duração: {len(a)/1000:.1f}s | dBFS: {a.dBFS:.1f} | Canais: {a.channels} | SR: {a.frame_rate}Hz')
"
```
- Duração ideal: **5–15 segundos**
- dBFS ideal: entre **-20 e -10 dBFS**
- Deve ser **mono** (1 canal), 22050 Hz

### 3. Teste rápido de síntese
```bash
.venv/bin/python -c "
import yaml
with open('config.yaml') as f:
    cfg = yaml.safe_load(f)
from modules.tts_narrator import TTSNarrator
n = TTSNarrator(cfg)
n.sintetizar_cena('Olá, este é um teste de síntese de voz em português.', '/tmp/teste_tts.wav')
print('Gerado em /tmp/teste_tts.wav')
"
```

### 4. Analise o áudio gerado
```bash
.venv/bin/python -c "
from pydub import AudioSegment
from pydub.silence import detect_silence
a = AudioSegment.from_wav('/tmp/teste_tts.wav')
print(f'Duração: {len(a)/1000:.1f}s | dBFS: {a.dBFS:.1f}')
silences = detect_silence(a, min_silence_len=200, silence_thresh=-40)
print(f'Pausas >200ms: {len(silences)} | Total silêncio: {sum(e-s for s,e in silences)/1000:.1f}s')
"
```

## Erros comuns e soluções

| Sintoma | Causa | Solução |
|---|---|---|
| Áudio "aaaa" em loop | DynamicCache bug (patch não aplicou) | Verificar log "Patch DynamicCache aplicado" |
| Voz feminina (Daisy) | `minha_voz.wav` não encontrada | Confirmar path `assets/voices/minha_voz.wav` |
| MRO error no import | transformers 4.35-4.56 | `pip install "transformers>=4.57.0"` |
| ImportError torchcodec | torchaudio >=2.5 sem patch | Patch torchaudio.load já em tts_narrator.py |
| Tom robótico/staccato | temperature=1.0 ou speed errada | Ajustar `generation.temperature: 0.75` no config.yaml |
| Chiados/hiss | Sem filtros, noise gate inativo | Verificar se scipy está instalado |
| Silêncio longo entre frases | Pausas fixas antigas | Código usa pausas por pontuação: . =380ms, ! =320ms |

## Parâmetros de naturalidade (config.yaml)
```yaml
tts:
  speed: 1.0          # não altere para naturalidade — use temperature
  generation:
    temperature: 0.75  # 0.6=robótico, 0.75=natural, 0.9=expressivo
    top_k: 50
    top_p: 0.85
    repetition_penalty: 1.1
```

## Patches ativos no código
- **torchaudio.load**: substituído por soundfile (topo de tts_narrator.py)
- **DynamicCache**: `prepare_inputs_for_generation` usa `get_seq_length()` para detectar cache vazio
- Ambos aplicados automaticamente no carregamento do modelo
