"""
tts_narrator.py
Sintetiza voz usando Coqui TTS (CPU).
Suporta clonagem de voz via XTTS v2 quando voice_sample é fornecido.
"""

# ── Patch de compatibilidade ──────────────────────────────────────────────────
# torchaudio >= 2.5 usa torchcodec como backend padrão (não instalado).
# torchaudio 2.10 ignora o parâmetro `backend` e chama load_with_torchcodec
# incondicionalmente. Substituímos torchaudio.load por implementação própria
# com soundfile, que já está disponível no requirements.
try:
    import torchaudio as _ta
    import soundfile as _sf
    import torch as _torch
    import numpy as _np

    def _load_via_soundfile(uri, frame_offset=0, num_frames=-1,
                            normalize=True, channels_first=True,
                            format=None, buffer_size=4096, backend=None):
        data, sample_rate = _sf.read(str(uri), dtype="float32", always_2d=True)
        if frame_offset > 0:
            data = data[frame_offset:]
        if num_frames > 0:
            data = data[:num_frames]
        tensor = _torch.from_numpy(data.T if channels_first else data)
        return tensor, sample_rate

    _ta.load = _load_via_soundfile
except Exception:
    pass
# ─────────────────────────────────────────────────────────────────────────────

import os
import re
import logging
import tempfile
from pathlib import Path
from typing import List
from pydub import AudioSegment
from pydub.effects import compress_dynamic_range, normalize

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[TTSNarrator] %(message)s")

# Modelo recomendado para clonagem de voz
MODELO_CLONAGEM = "tts_models/multilingual/multi-dataset/xtts_v2"
IDIOMA_PADRAO = "pt"


class TTSNarrator:
    def __init__(self, config: dict):
        self.config = config
        self.tts_cfg = config.get("tts", {})
        self.model_name = self.tts_cfg.get("model", MODELO_CLONAGEM)
        # Trata string vazia como None (sem speaker explícito → auto-seleção)
        self.speaker = self.tts_cfg.get("speaker", None) or None
        self.speed = self.tts_cfg.get("speed", 1.0)
        self.language = self.tts_cfg.get("language", IDIOMA_PADRAO)

        # Caminho para o áudio de referência de voz (clonagem)
        voice_sample_raw = self.tts_cfg.get("voice_sample", None)
        self.voice_sample = str(Path(voice_sample_raw).resolve()) if voice_sample_raw else None

        # Modo clonagem: ativo quando voice_sample existe e é um arquivo válido
        self.modo_clonagem = False
        if self.voice_sample:
            if Path(self.voice_sample).is_file():
                self.modo_clonagem = True
                log.info(f"Modo clonagem de voz ATIVO: {self.voice_sample}")
            else:
                log.warning(f"voice_sample configurado mas arquivo não encontrado: {self.voice_sample}")
                log.warning("Usando TTS padrão sem clonagem.")

        self._tts = None  # lazy load

    def _get_tts(self):
        """Carrega o modelo TTS (lazy loading para economizar memória)."""
        if self._tts is None:
            from TTS.api import TTS
            log.info(f"Carregando modelo TTS: {self.model_name}")
            # gpu=False garante CPU — RX580/AMD tem suporte ROCm instável
            self._tts = TTS(model_name=self.model_name, progress_bar=True, gpu=False)
            log.info("Modelo TTS carregado!")

            # ── Patch DynamicCache / transformers >= 4.46 ────────────────────────
            # generate() pré-aloca um DynamicCache VAZIO antes do 1º forward pass.
            # DynamicCache não é None, então XTTS trunca gpt_inputs para 1 token
            # (só o start_audio_token) sem contexto → modelo gera lixo/aaaa.
            # Fix: verifica conteúdo real do cache antes de truncar input_ids.
            try:
                from TTS.tts.layers.xtts.gpt_inference import GPT2InferenceModel

                def _prepare_inputs_patched(self_gpt, input_ids, past_key_values=None, **kwargs):
                    token_type_ids = kwargs.get("token_type_ids", None)
                    if not self_gpt.kv_cache:
                        past_key_values = None

                    # DynamicCache pode estar pré-alocado mas vazio no passo 0
                    _has_cache = False
                    if past_key_values is not None:
                        if hasattr(past_key_values, "get_seq_length"):
                            _has_cache = past_key_values.get_seq_length() > 0
                        elif isinstance(past_key_values, (tuple, list)) and len(past_key_values) > 0:
                            try:
                                _has_cache = past_key_values[0][0].shape[-2] > 0
                            except Exception:
                                _has_cache = True  # assume cache válido

                    if _has_cache:
                        input_ids = input_ids[:, -1].unsqueeze(-1)
                        if token_type_ids is not None:
                            token_type_ids = token_type_ids[:, -1].unsqueeze(-1)

                    attention_mask = kwargs.get("attention_mask", None)
                    position_ids = kwargs.get("position_ids", None)

                    if attention_mask is not None and position_ids is None:
                        position_ids = attention_mask.long().cumsum(-1) - 1
                        position_ids.masked_fill_(attention_mask == 0, 1)
                        if _has_cache:
                            position_ids = position_ids[:, -1].unsqueeze(-1)
                    else:
                        position_ids = None

                    return {
                        "input_ids": input_ids,
                        "past_key_values": past_key_values,
                        "use_cache": kwargs.get("use_cache"),
                        "position_ids": position_ids,
                        "attention_mask": attention_mask,
                        "token_type_ids": token_type_ids,
                    }

                GPT2InferenceModel.prepare_inputs_for_generation = _prepare_inputs_patched
                log.info("Patch aplicado: GPT2InferenceModel (fix DynamicCache transformers>=4.46)")
            except Exception as e:
                log.warning(f"Patch DynamicCache não aplicado: {e}")
            # ─────────────────────────────────────────────────────────────────────

            # Auto-seleciona speaker se modelo é multi-speaker e nenhum foi configurado
            if not self.modo_clonagem and not self.speaker:
                speakers = list(getattr(self._tts, "speakers", None) or [])

                # Tenta obter speakers via synthesizer internamente (XTTS v2)
                if not speakers:
                    try:
                        mgr = self._tts.synthesizer.tts_model.speaker_manager
                        speakers = list(mgr.name_to_id.keys())
                    except Exception:
                        pass

                if speakers:
                    # Prefere speakers com sotaque mais próximo do português
                    preferidos = ["Ana Florence", "Gilberto Mathias", "Claribel Dervla", "Daisy Studious"]
                    self.speaker = next(
                        (s for s in preferidos if s in speakers),
                        speakers[0]
                    )
                    log.info(f"Speaker auto-selecionado: {self.speaker}")
                else:
                    is_multi = getattr(self._tts, "is_multi_speaker", False)
                    if is_multi or "xtts" in self.model_name.lower():
                        # Fallback hardcoded — XTTS v2 exige speaker mesmo sem lista acessível
                        self.speaker = "Daisy Studious"
                        log.warning(f"Lista de speakers inacessível — usando fallback: {self.speaker}")
                    else:
                        log.warning("Modelo não tem lista de speakers — tentando sem speaker.")

        return self._tts

    def _limpar_texto(self, texto: str) -> str:
        """Remove caracteres problemáticos para TTS."""
        # Remove emojis
        texto = re.sub(r'[^\x00-\x7F\u00C0-\u024F\u1E00-\u1EFF]', '', texto)
        # Remove múltiplos espaços/quebras
        texto = re.sub(r'\s+', ' ', texto)
        # Remove markdown
        texto = re.sub(r'\*+|#+|_{2,}|`+', '', texto)
        # Normaliza pontuação
        texto = texto.replace('...', '.').replace('..', '.')
        return texto.strip()

    def _dividir_em_chunks(self, texto: str, max_chars: int = 200) -> List[str]:
        """
        Divide texto longo em chunks menores para o TTS processar melhor.
        XTTS v2 performa melhor com chunks menores (~200 chars).
        Quebra em pontos finais, sem cortar frases no meio.
        """
        sentencas = re.split(r'(?<=[.!?])\s+', texto)
        chunks = []
        atual = ""

        for s in sentencas:
            if len(atual) + len(s) < max_chars:
                atual += (" " if atual else "") + s
            else:
                if atual:
                    chunks.append(atual.strip())
                atual = s

        if atual:
            chunks.append(atual.strip())

        return [c for c in chunks if c.strip()]

    def _sintetizar_chunk(self, tts, chunk: str, output_path: str):
        """Sintetiza um único chunk de texto, com ou sem clonagem de voz."""
        if self.modo_clonagem:
            tts.tts_to_file(
                text=chunk,
                speaker_wav=self.voice_sample,
                language=self.language,
                file_path=output_path,
                speed=self.speed,
            )
        else:
            kwargs = dict(
                text=chunk,
                file_path=output_path,
                speed=self.speed,
            )
            if self.speaker:
                kwargs["speaker"] = self.speaker
            # XTTS v2 é multilingual e sempre requer language
            if getattr(tts, "is_multi_lingual", False) or "xtts" in self.model_name.lower():
                kwargs["language"] = self.language
            try:
                tts.tts_to_file(**kwargs)
            except ValueError as e:
                # Fallback: se ainda faltar speaker, tenta com speaker hardcoded
                if "speaker" in str(e).lower() and "speaker" not in kwargs:
                    log.warning(f"Erro de speaker — aplicando fallback 'Daisy Studious': {e}")
                    kwargs["speaker"] = "Daisy Studious"
                    tts.tts_to_file(**kwargs)
                else:
                    raise

    def _pos_processar(self, audio: AudioSegment) -> AudioSegment:
        """
        Pós-processamento aplicado UMA VEZ no áudio completo:
        - Normaliza ao pico (0 dBFS)
        - Compressão dinâmica suave (soa mais "broadcast")
        - Ganho +5 dB para atingir ~-18 dBFS médio (adequado para YouTube)
        - Fade in/out no início e fim do trecho
        """
        audio = normalize(audio)
        audio = compress_dynamic_range(audio, threshold=-20.0, ratio=2.5, attack=5.0, release=50.0)
        audio = audio + 5  # +5 dB para compensar compressão — alvo ~-18 dBFS médio
        audio = audio.fade_in(30).fade_out(60)
        return audio

    def sintetizar_cena(self, texto: str, output_path: str) -> str:
        """
        Sintetiza uma cena completa. Se o texto for muito longo,
        divide em chunks e concatena o áudio.
        """
        tts = self._get_tts()
        texto = self._limpar_texto(texto)

        if not texto:
            log.warning("Texto vazio, gerando silêncio")
            silencio = AudioSegment.silent(duration=1000)
            silencio.export(output_path, format="wav")
            return output_path

        chunks = self._dividir_em_chunks(texto)
        log.info(f"Sintetizando {len(chunks)} chunk(s) de texto" +
                 (" [modo clonagem de voz]" if self.modo_clonagem else "") + "...")

        if len(chunks) == 1:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                self._sintetizar_chunk(tts, chunks[0], tmp_path)
                audio = AudioSegment.from_wav(tmp_path)
                audio = self._pos_processar(audio)
                audio.export(output_path, format="wav")
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        else:
            audio_final = AudioSegment.empty()
            pausa = AudioSegment.silent(duration=150)

            for i, chunk in enumerate(chunks):
                log.info(f"  Chunk {i+1}/{len(chunks)}: {chunk[:60]}...")
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_path = tmp.name

                try:
                    self._sintetizar_chunk(tts, chunk, tmp_path)
                    seg = AudioSegment.from_wav(tmp_path)
                    # Fade curtíssimo só para evitar cliques na junção
                    seg = seg.fade_in(5).fade_out(5)
                    audio_final += seg + pausa
                finally:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)

            # Pós-processamento uma única vez no áudio completo
            audio_final = self._pos_processar(audio_final)
            audio_final.export(output_path, format="wav")

        log.info(f"Audio salvo: {output_path}")
        return output_path

    def sintetizar_roteiro_completo(self, roteiro_texto: str, output_path: str) -> str:
        """Sintetiza o roteiro completo em um único arquivo de áudio."""
        log.info("Sintetizando narração completa do roteiro...")
        return self.sintetizar_cena(roteiro_texto, output_path)

    def sintetizar_por_cenas(self, cenas: list, pasta_output: str) -> List[str]:
        """
        Sintetiza cada cena separadamente.
        Retorna lista de caminhos dos arquivos de áudio.
        """
        os.makedirs(pasta_output, exist_ok=True)
        audios = []

        for cena in cenas:
            audio_path = os.path.join(pasta_output, f"cena_{cena.numero:02d}.wav")
            log.info(f"Sintetizando cena {cena.numero}: {cena.titulo}")
            self.sintetizar_cena(cena.naracao, audio_path)
            audios.append(audio_path)

        return audios

    def listar_modelos_pt(self):
        """Lista modelos TTS disponíveis em português."""
        from TTS.api import TTS
        print("\nModelos disponíveis em português:")
        for m in TTS.list_models():
            if "/pt/" in m or "pt_" in m or "multilingual" in m:
                print(f"  - {m}")
