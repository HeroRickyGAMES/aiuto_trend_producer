"""
tts_narrator.py
Sintetiza voz usando Coqui TTS (CPU) com XTTS v2.
Otimizado para naturalidade: prosódia variável, pausas naturais,
filtros de áudio para qualidade de broadcast.
"""

# ── Patch torchaudio >= 2.5 ───────────────────────────────────────────────────
# torchaudio 2.10 usa torchcodec por padrão (não instalado).
# Substituímos torchaudio.load por implementação soundfile.
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
from typing import List, Optional

import numpy as np
from pydub import AudioSegment
from pydub.effects import compress_dynamic_range, normalize

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[TTSNarrator] %(message)s")

MODELO_CLONAGEM = "tts_models/multilingual/multi-dataset/xtts_v2"
IDIOMA_PADRAO = "pt"

# Duração de pausa (ms) conforme pontuação que termina a sentença
_PAUSAS_MS = {
    ".": 380,   # ponto final — pausa de respiração
    "!": 320,   # exclamação
    "?": 320,   # interrogação
    ";": 220,   # ponto-e-vírgula
    ":": 180,   # dois-pontos
    ",": 90,    # vírgula (usado quando dividimos em sub-frases)
}
_PAUSA_DEFAULT_MS = 250


class TTSNarrator:
    def __init__(self, config: dict):
        self.config = config
        self.tts_cfg = config.get("tts", {})
        self.model_name = self.tts_cfg.get("model", MODELO_CLONAGEM)
        self.speaker = self.tts_cfg.get("speaker", None) or None
        self.speed = float(self.tts_cfg.get("speed", 1.0))
        self.language = self.tts_cfg.get("language", IDIOMA_PADRAO)

        # Parâmetros de geração para prosódia natural
        gen_cfg = self.tts_cfg.get("generation", {})
        self.temperature    = float(gen_cfg.get("temperature", 0.75))
        self.top_k          = int(gen_cfg.get("top_k", 50))
        self.top_p          = float(gen_cfg.get("top_p", 0.85))
        self.rep_penalty    = float(gen_cfg.get("repetition_penalty", 1.1))

        # Voz de referência para clonagem
        voice_sample_raw = self.tts_cfg.get("voice_sample", None)
        self._voice_sample_original = str(Path(voice_sample_raw).resolve()) if voice_sample_raw else None
        self.voice_sample = self._voice_sample_original  # pode ser substituído pelo limpo
        self._voice_sample_tmp = None   # temp file da referência limpa (apagado no final)
        self.modo_clonagem = False
        if self.voice_sample and Path(self.voice_sample).is_file():
            self.modo_clonagem = True
            log.info(f"Modo clonagem ATIVO: {self.voice_sample}")
            # Pré-processa a referência: extrai melhor trecho + noise reduction
            self.voice_sample = self._preparar_referencia_voz(self.voice_sample)
        elif self.voice_sample:
            log.warning(f"voice_sample não encontrado: {self.voice_sample} — usando TTS padrão")

        self._tts = None

    # ─────────────────────────────────────────────────────────────────────────
    # Preparação da referência de voz
    # ─────────────────────────────────────────────────────────────────────────

    def _preparar_referencia_voz(self, wav_path: str) -> str:
        """
        Limpa o áudio de referência antes de passar para o XTTS:
        1. Extrai os primeiros 30s de fala ativa (ignora silêncio inicial)
        2. Converte para mono 22050 Hz
        3. Aplica subtração espectral para reduzir ruído de fundo e hiss
        4. Normaliza volume
        Retorna caminho para arquivo temporário limpo.
        """
        try:
            import soundfile as sf
            from scipy.signal import stft, istft
            from scipy.signal import butter, filtfilt
            from pydub.silence import detect_nonsilent

            log.info("Preparando referência de voz: limpando ruído...")

            # 1. Carrega e converte para mono 22050 Hz
            audio = AudioSegment.from_file(wav_path)
            audio = audio.set_channels(1).set_frame_rate(22050)

            # 2. Extrai até 30s de fala ativa (pula silêncio inicial/final)
            partes_fala = detect_nonsilent(audio, min_silence_len=400, silence_thresh=-38)
            if partes_fala:
                inicio = partes_fala[0][0]
                # Pega até 30s a partir do primeiro trecho de fala
                fim = min(inicio + 30_000, partes_fala[-1][1])
                trecho = audio[inicio:fim]
            else:
                trecho = audio[:30_000]  # fallback: primeiros 30s

            log.info(f"  Trecho de referência: {len(trecho)/1000:.1f}s de fala extraídos")

            # 3. Converte para numpy float32
            samples = np.array(trecho.get_array_of_samples(), dtype=np.float32) / 32768.0
            sr = trecho.frame_rate

            # 4. High-pass 80 Hz — remove rumble/vibração de fundo
            nyq = sr / 2.0
            b, a = butter(2, 80.0 / nyq, btype='high')
            samples = filtfilt(b, a, samples)

            # 5. Subtração espectral — reduz ruído estacionário (hiss, sala, AC)
            # Busca um trecho de silêncio REAL no ARQUIVO ORIGINAL para estimar o ruído.
            # Isso evita usar fala como referência de ruído (o erro mais comum).
            noise_ref = None

            # Tenta primeiro: silêncio no arquivo original (antes da fala)
            silencio_orig = detect_nonsilent(
                AudioSegment.from_file(wav_path).set_channels(1).set_frame_rate(sr),
                min_silence_len=300, silence_thresh=-38
            )
            audio_orig_mono = AudioSegment.from_file(wav_path).set_channels(1).set_frame_rate(sr)
            if silencio_orig and silencio_orig[0][0] > 300:
                # Há silêncio antes da primeira fala
                sil_inicio = 0
                sil_fim = silencio_orig[0][0]  # ms
                seg_sil = audio_orig_mono[sil_inicio:sil_fim]
                noise_ref = np.array(seg_sil.get_array_of_samples(), dtype=np.float32) / 32768.0
                log.info(f"  Ruído estimado de {sil_fim}ms de silêncio pré-fala do original")
            else:
                # Procura silêncios entre palavras no trecho extraído
                from pydub.silence import detect_silence as _det_sil
                sils = _det_sil(trecho, min_silence_len=200, silence_thresh=-42)
                if sils:
                    s0, e0 = sils[0]
                    seg_sil = trecho[s0:e0]
                    noise_ref = np.array(seg_sil.get_array_of_samples(), dtype=np.float32) / 32768.0
                    log.info(f"  Ruído estimado de pausa interna ({(e0-s0)}ms)")
                else:
                    # Fallback: primeiros 200ms do trecho (melhor que nada)
                    n_fb = int(sr * 0.2)
                    noise_ref = samples[:n_fb]
                    log.info("  Ruído estimado dos primeiros 200ms (fallback)")

            n_noise = len(noise_ref)

            # STFT
            nperseg = 1024
            noverlap = 768
            f, t, Zxx = stft(samples, fs=sr, nperseg=nperseg, noverlap=noverlap)
            _, _, Zxx_n = stft(noise_ref, fs=sr, nperseg=nperseg, noverlap=noverlap)

            # Perfil de ruído médio (com margem de segurança 1.5x)
            noise_profile = np.mean(np.abs(Zxx_n), axis=1, keepdims=True) * 1.5

            # Subtração espectral com flooring (não vai abaixo de 15% do original)
            mag = np.abs(Zxx)
            phase = np.angle(Zxx)
            mag_clean = np.maximum(mag - noise_profile, 0.15 * mag)

            # Suaviza transições (reduz "musical noise" = chiado residual metálico)
            from scipy.ndimage import uniform_filter
            mag_clean = uniform_filter(mag_clean, size=(1, 3))

            # Reconstrói sinal
            Zxx_clean = mag_clean * np.exp(1j * phase)
            _, samples_clean = istft(Zxx_clean, fs=sr, nperseg=nperseg, noverlap=noverlap)
            samples_clean = np.clip(samples_clean[:len(samples)], -1.0, 1.0).astype(np.float32)

            # 6. Normaliza para -14 dBFS (referência forte e limpa para o XTTS)
            peak = np.max(np.abs(samples_clean))
            if peak > 0:
                target_peak = 10 ** (-14.0 / 20.0)
                samples_clean = samples_clean * (target_peak / peak)

            # Salva em arquivo temporário
            tmp = tempfile.NamedTemporaryFile(suffix="_ref_limpa.wav", delete=False)
            sf.write(tmp.name, samples_clean, sr)
            self._voice_sample_tmp = tmp.name

            # Diagnóstico: mede nível de ruído antes/depois
            rms_antes = np.sqrt(np.mean(samples[:n_noise] ** 2))
            rms_depois = np.sqrt(np.mean(samples_clean[:n_noise] ** 2))
            reducao_db = 20 * np.log10(rms_depois / (rms_antes + 1e-10))
            log.info(f"  Noise reduction: {reducao_db:.1f} dB | ref salva em {tmp.name}")

            return tmp.name

        except Exception as e:
            log.warning(f"Preparação de referência falhou ({e}) — usando arquivo original")
            return wav_path

    def __del__(self):
        """Limpa arquivo temporário da referência ao destruir o objeto."""
        if self._voice_sample_tmp and os.path.exists(self._voice_sample_tmp):
            try:
                os.unlink(self._voice_sample_tmp)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # Carregamento do modelo
    # ─────────────────────────────────────────────────────────────────────────

    def _get_tts(self):
        if self._tts is not None:
            return self._tts

        from TTS.api import TTS
        log.info(f"Carregando modelo TTS: {self.model_name}")
        self._tts = TTS(model_name=self.model_name, progress_bar=True, gpu=False)
        log.info("Modelo TTS carregado!")

        # ── Patch DynamicCache / transformers >= 4.46 ────────────────────────
        # generate() pré-aloca DynamicCache VAZIO → XTTS trunca gpt_inputs
        # para 1 token no passo 0 → sem contexto → gera lixo.
        # Fix: verifica get_seq_length() antes de truncar.
        try:
            from TTS.tts.layers.xtts.gpt_inference import GPT2InferenceModel

            def _prepare_inputs_patched(self_gpt, input_ids, past_key_values=None, **kwargs):
                token_type_ids = kwargs.get("token_type_ids", None)
                if not self_gpt.kv_cache:
                    past_key_values = None

                _has_cache = False
                if past_key_values is not None:
                    if hasattr(past_key_values, "get_seq_length"):
                        _has_cache = past_key_values.get_seq_length() > 0
                    elif isinstance(past_key_values, (tuple, list)) and len(past_key_values) > 0:
                        try:
                            _has_cache = past_key_values[0][0].shape[-2] > 0
                        except Exception:
                            _has_cache = True

                if _has_cache:
                    input_ids = input_ids[:, -1].unsqueeze(-1)
                    if token_type_ids is not None:
                        token_type_ids = token_type_ids[:, -1].unsqueeze(-1)

                attention_mask = kwargs.get("attention_mask", None)
                position_ids   = kwargs.get("position_ids",   None)

                if attention_mask is not None and position_ids is None:
                    position_ids = attention_mask.long().cumsum(-1) - 1
                    position_ids.masked_fill_(attention_mask == 0, 1)
                    if _has_cache:
                        position_ids = position_ids[:, -1].unsqueeze(-1)
                else:
                    position_ids = None

                return {
                    "input_ids":      input_ids,
                    "past_key_values": past_key_values,
                    "use_cache":       kwargs.get("use_cache"),
                    "position_ids":    position_ids,
                    "attention_mask":  attention_mask,
                    "token_type_ids":  token_type_ids,
                }

            GPT2InferenceModel.prepare_inputs_for_generation = _prepare_inputs_patched
            log.info("Patch DynamicCache aplicado (fix transformers>=4.46)")
        except Exception as e:
            log.warning(f"Patch DynamicCache não aplicado: {e}")
        # ─────────────────────────────────────────────────────────────────────

        # Auto-seleciona speaker para modo sem clonagem
        if not self.modo_clonagem and not self.speaker:
            speakers = list(getattr(self._tts, "speakers", None) or [])
            if not speakers:
                try:
                    mgr = self._tts.synthesizer.tts_model.speaker_manager
                    speakers = list(mgr.name_to_id.keys())
                except Exception:
                    pass
            if speakers:
                preferidos = ["Ana Florence", "Gilberto Mathias", "Claribel Dervla"]
                self.speaker = next(
                    (s for s in preferidos if s in speakers),
                    speakers[0]
                )
                log.info(f"Speaker auto-selecionado: {self.speaker}")
            elif "xtts" in self.model_name.lower():
                self.speaker = "Daisy Studious"
                log.warning(f"Fallback speaker: {self.speaker}")

        return self._tts

    # ─────────────────────────────────────────────────────────────────────────
    # Pré-processamento de texto
    # ─────────────────────────────────────────────────────────────────────────

    def _limpar_texto(self, texto: str) -> str:
        """Remove emojis, markdown, normaliza espaços."""
        texto = re.sub(r'[^\x00-\x7F\u00C0-\u024F\u1E00-\u1EFF]', '', texto)
        texto = re.sub(r'\*+|#+|_{2,}|`+|\[|\]', '', texto)
        texto = re.sub(r'\s+', ' ', texto)
        return texto.strip()

    def _expandir_abreviacoes(self, texto: str) -> str:
        """Expande abreviações comuns do português para fala natural."""
        subs = [
            (r'\bDr\.(?=\s)', 'Doutor '),
            (r'\bDra\.(?=\s)', 'Doutora '),
            (r'\bProf\.(?=\s)', 'Professor '),
            (r'\bProfa\.(?=\s)', 'Professora '),
            (r'\betc\.', 'etcetera'),
            (r'\bvs\.', 'versus'),
            (r'\bex\.(?=\s)', 'por exemplo '),
            (r'\bpq\b', 'porque'),
            (r'\btb\b', 'também'),
            (r'\bséc\.\s*(\w+)', r'século \1'),
            (r'(\d+)\s*km\b', r'\1 quilômetros'),
            (r'(\d+)\s*kg\b', r'\1 quilogramas'),
            (r'(\d+)\s*m\b', r'\1 metros'),
            (r'(\d+)\s*%', r'\1 por cento'),
            (r'(\d+)\s*°C', r'\1 graus Celsius'),
        ]
        for pattern, repl in subs:
            texto = re.sub(pattern, repl, texto, flags=re.IGNORECASE)
        return texto

    def _numeros_por_extenso(self, texto: str) -> str:
        """
        Converte números inteiros simples (1-999) para palavras em pt-BR.
        Conservador: não toca decimais, anos (1800-2099), percentuais já
        tratados em _expandir_abreviacoes, nem números com separadores.
        """
        try:
            from num2words import num2words

            def _conv(m):
                raw = m.group(0)
                try:
                    val = int(raw)
                    # Preservar anos e qualquer número >= 1000
                    if val >= 1000:
                        return raw
                    return num2words(val, lang='pt_BR')
                except Exception:
                    return raw

            # Só inteiros isolados — não toca decimais (13.8, 6,5), separadores (300.000) ou anos
            texto = re.sub(r'(?<![,.\d])\b([1-9]\d{0,2})\b(?![.,\d])', _conv, texto)
        except ImportError:
            pass
        return texto

    def _preparar_texto(self, texto: str) -> str:
        """Pipeline completo de preparação de texto para síntese natural."""
        texto = self._limpar_texto(texto)
        texto = self._expandir_abreviacoes(texto)
        texto = self._numeros_por_extenso(texto)
        # Normaliza pontuação: elipses → ponto, hífens duplos → vírgula
        texto = re.sub(r'\.{2,}', '.', texto)
        texto = re.sub(r'\s*--\s*', ', ', texto)
        texto = re.sub(r'\s+', ' ', texto)
        return texto.strip()

    # ─────────────────────────────────────────────────────────────────────────
    # Divisão em sentenças naturais
    # ─────────────────────────────────────────────────────────────────────────

    def _dividir_em_sentencas(self, texto: str, max_chars: int = 230) -> List[str]:
        """
        Divide em sentenças completas respeitando pontuação natural.
        Não parte no meio de frases — garante que cada chunk seja
        uma unidade de fala coerente para o XTTS.
        """
        # Separa nas fronteiras de sentença (., !, ?) mantendo o pontuador
        partes = re.split(r'(?<=[.!?])\s+', texto)

        sentencas = []
        buffer = ""

        for parte in partes:
            if not parte.strip():
                continue
            if len(buffer) + len(parte) + 1 <= max_chars:
                buffer = (buffer + " " + parte).strip() if buffer else parte
            else:
                if buffer:
                    sentencas.append(buffer.strip())
                # Sentença maior que max_chars: divide em cláusulas por vírgula
                if len(parte) > max_chars:
                    clausulas = re.split(r'(?<=,)\s+', parte)
                    sub = ""
                    for c in clausulas:
                        if len(sub) + len(c) + 1 <= max_chars:
                            sub = (sub + " " + c).strip() if sub else c
                        else:
                            if sub:
                                sentencas.append(sub.strip())
                            sub = c
                    buffer = sub
                else:
                    buffer = parte

        if buffer:
            sentencas.append(buffer.strip())

        return [s for s in sentencas if s.strip()]

    # ─────────────────────────────────────────────────────────────────────────
    # Síntese
    # ─────────────────────────────────────────────────────────────────────────

    def _kwargs_geracao(self) -> dict:
        """
        Parâmetros de geração para prosódia natural.
        temperature > 0 + do_sample=True = variação rítmica humana.
        """
        return dict(
            temperature=self.temperature,
            top_k=self.top_k,
            top_p=self.top_p,
            repetition_penalty=self.rep_penalty,
            do_sample=True,
        )

    def _sintetizar_sentenca(self, tts, sentenca: str, output_path: str):
        """Sintetiza uma sentença com parâmetros de naturalidade."""
        gen_kwargs = self._kwargs_geracao()

        if self.modo_clonagem:
            tts.tts_to_file(
                text=sentenca,
                speaker_wav=self.voice_sample,
                language=self.language,
                file_path=output_path,
                speed=self.speed,
                split_sentences=False,   # já dividimos nós mesmos
                **gen_kwargs,
            )
        else:
            kwargs = dict(
                text=sentenca,
                file_path=output_path,
                speed=self.speed,
                split_sentences=False,
                **gen_kwargs,
            )
            if self.speaker:
                kwargs["speaker"] = self.speaker
            if getattr(tts, "is_multi_lingual", False) or "xtts" in self.model_name.lower():
                kwargs["language"] = self.language
            try:
                tts.tts_to_file(**kwargs)
            except ValueError as e:
                if "speaker" in str(e).lower() and "speaker" not in kwargs:
                    log.warning(f"Fallback speaker 'Daisy Studious': {e}")
                    kwargs["speaker"] = "Daisy Studious"
                    tts.tts_to_file(**kwargs)
                else:
                    raise

    # ─────────────────────────────────────────────────────────────────────────
    # Processamento de áudio
    # ─────────────────────────────────────────────────────────────────────────

    def _strip_silence(self, audio: AudioSegment,
                       head_ms: int = 40, tail_ms: int = 80,
                       thresh_db: float = -48.0) -> AudioSegment:
        """
        Remove silêncio excessivo de início e fim do chunk.
        Mantém uma margem head/tail para não cortar as consoantes.
        """
        from pydub.silence import detect_leading_silence
        lead = detect_leading_silence(audio, silence_threshold=thresh_db)
        lead = max(0, lead - head_ms)

        rev = audio.reverse()
        trail = detect_leading_silence(rev, silence_threshold=thresh_db)
        trail = max(0, trail - tail_ms)

        end = len(audio) - trail if trail > 0 else len(audio)
        return audio[lead:end] if end > lead else audio

    def _pausa_por_pontuacao(self, sentenca: str) -> AudioSegment:
        """Gera pausa de duração natural baseada no último caractere."""
        ultimo = sentenca.rstrip()[-1] if sentenca.rstrip() else '.'
        ms = _PAUSAS_MS.get(ultimo, _PAUSA_DEFAULT_MS)
        return AudioSegment.silent(duration=ms)

    def _aplicar_filtros(self, audio: AudioSegment) -> AudioSegment:
        """
        Filtros para qualidade de broadcast:
        - High-pass 80 Hz (remove rumble e DC offset)
        - Noise gate suave (atenua ruído entre falas)
        """
        try:
            from scipy import signal as sp_signal

            # Converte para float64
            samples = np.array(audio.get_array_of_samples(), dtype=np.float64)
            is_stereo = audio.channels == 2
            if is_stereo:
                samples = samples.reshape((-1, 2))

            sr = audio.frame_rate
            max_val = float(2 ** (audio.sample_width * 8 - 1))
            s_norm = samples / max_val

            # High-pass Butterworth de 2ª ordem a 80 Hz
            nyq = sr / 2.0
            b, a = sp_signal.butter(2, 80.0 / nyq, btype='high')

            if is_stereo:
                filtered = np.column_stack([
                    sp_signal.filtfilt(b, a, s_norm[:, 0]),
                    sp_signal.filtfilt(b, a, s_norm[:, 1]),
                ])
                filtered = filtered.flatten()
            else:
                filtered = sp_signal.filtfilt(b, a, s_norm)

            # Noise gate: RMS por janela de 20ms
            win = max(1, int(sr * 0.02))
            gate_thresh = 10 ** (-52.0 / 20.0)  # -52 dBFS
            for i in range(0, len(filtered), win):
                chunk = filtered[i:i + win]
                rms = np.sqrt(np.mean(chunk ** 2)) if len(chunk) > 0 else 0.0
                if rms < gate_thresh:
                    filtered[i:i + win] *= 0.04   # -28 dB de atenuação

            # Converte de volta
            out = np.clip(filtered * max_val, -max_val, max_val - 1)
            out = out.astype(np.int16 if audio.sample_width == 2 else np.int32)
            return audio._spawn(out.tobytes())

        except Exception as e:
            log.warning(f"Filtros de áudio não aplicados: {e}")
            return audio

    def _pos_processar(self, audio: AudioSegment) -> AudioSegment:
        """
        Cadeia final de processamento para qualidade broadcast:
        filtros → normaliza → compressão dinâmica suave → ganho
        """
        audio = self._aplicar_filtros(audio)
        audio = normalize(audio)
        # Compressão leve — preserva dinâmica da voz, controla picos
        audio = compress_dynamic_range(
            audio,
            threshold=-22.0,
            ratio=2.2,
            attack=8.0,
            release=80.0,
        )
        # Gain para -16 dBFS médio (padrão YouTube/podcast)
        target_db = -16.0
        gain = target_db - audio.dBFS
        audio = audio.apply_gain(min(gain, 6.0))  # max +6 dB para não saturar
        audio = audio.fade_in(20).fade_out(80)
        return audio

    # ─────────────────────────────────────────────────────────────────────────
    # API pública
    # ─────────────────────────────────────────────────────────────────────────

    def sintetizar_cena(self, texto: str, output_path: str) -> str:
        """
        Sintetiza uma cena completa.
        1. Prepara o texto (abreviações, números por extenso)
        2. Divide em sentenças naturais
        3. Sintetiza cada sentença com parâmetros de naturalidade
        4. Monta o áudio com pausas baseadas em pontuação
        5. Aplica pós-processamento
        """
        tts = self._get_tts()
        texto = self._preparar_texto(texto)

        if not texto:
            log.warning("Texto vazio — gerando silêncio")
            AudioSegment.silent(duration=1000).export(output_path, format="wav")
            return output_path

        sentencas = self._dividir_em_sentencas(texto)
        modo_label = "[clonagem]" if self.modo_clonagem else "[speaker]"
        log.info(f"Sintetizando {len(sentencas)} sentença(s) {modo_label}...")

        segmentos: List[AudioSegment] = []

        for i, sent in enumerate(sentencas):
            log.info(f"  [{i+1}/{len(sentencas)}] {sent[:70]}{'…' if len(sent) > 70 else ''}")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                self._sintetizar_sentenca(tts, sent, tmp_path)
                seg = AudioSegment.from_wav(tmp_path)
                seg = self._strip_silence(seg)
                segmentos.append((sent, seg))
            except Exception as e:
                log.error(f"  Erro na sentença {i+1}: {e}")
                # Adiciona silêncio como fallback para não quebrar a cena
                segmentos.append((sent, AudioSegment.silent(duration=500)))
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        # Monta áudio com pausas naturais entre sentenças
        audio_final = AudioSegment.empty()
        for idx, (sent, seg) in enumerate(segmentos):
            audio_final += seg
            # Adiciona pausa após cada sentença (exceto a última)
            if idx < len(segmentos) - 1:
                audio_final += self._pausa_por_pontuacao(sent)

        # Pós-processamento único na faixa completa
        audio_final = self._pos_processar(audio_final)
        audio_final.export(output_path, format="wav")
        log.info(f"Áudio salvo: {output_path} ({len(audio_final)/1000:.1f}s)")
        return output_path

    def sintetizar_roteiro_completo(self, roteiro_texto: str, output_path: str) -> str:
        """Sintetiza o roteiro completo em um único arquivo."""
        log.info("Sintetizando narração completa...")
        return self.sintetizar_cena(roteiro_texto, output_path)

    def sintetizar_por_cenas(self, cenas: list, pasta_output: str) -> List[str]:
        """Sintetiza cada cena separadamente, retorna lista de caminhos."""
        os.makedirs(pasta_output, exist_ok=True)
        audios = []
        for cena in cenas:
            audio_path = os.path.join(pasta_output, f"cena_{cena.numero:02d}.wav")
            log.info(f"Sintetizando cena {cena.numero}: {cena.titulo}")
            self.sintetizar_cena(cena.naracao, audio_path)
            audios.append(audio_path)
        return audios

    def listar_modelos_pt(self):
        from TTS.api import TTS
        print("\nModelos disponíveis em português:")
        for m in TTS.list_models():
            if "/pt/" in m or "pt_" in m or "multilingual" in m:
                print(f"  - {m}")
