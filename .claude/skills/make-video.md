# make-video

Cria um vídeo completo no pipeline IA Video Creator.

## Uso
`/make-video [tema opcional]`

## O que fazer

1. Verifique se o ambiente virtual está ativo:
   ```bash
   source .venv/bin/activate
   ```

2. Se o usuário passou um tema, rode:
   ```bash
   python main.py --tema "<tema>"
   ```
   Se não passou tema, rode sem `--tema` para buscar trends automaticamente:
   ```bash
   python main.py
   ```
   Para processar **todos** os temas em batch sem interação:
   ```bash
   python main.py -a
   ```

3. Confirme que o Ollama está rodando antes de executar:
   ```bash
   ollama list
   ```
   Se não estiver, oriente o usuário a iniciar com `ollama serve`.

4. Após a execução, localize o vídeo gerado em `export/` e informe o caminho.

## Troubleshooting rápido

- **Ollama não responde**: `ollama serve` em outro terminal
- **TTS demora muito**: normal — XTTS v2 é pesado na CPU (Ryzen 5500 leva ~2-4 min por cena)
- **Sem trends**: o pipeline pede tema manual automaticamente
- **Erro de memória**: feche outros programas — XTTS usa ~4GB de RAM

## Passos do pipeline
1. Trends (Google + HN + NASA RSS)
2. Roteiro (Ollama/gemma2)
3. Mídia (Pexels API)
4. Narração (XTTS v2 com clonagem de voz)
5. Vídeo (moviepy)
6. Thumbnail + metadata