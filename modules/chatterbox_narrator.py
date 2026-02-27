"""
chatterbox_narrator.py
Narração TTS usando Chatterbox TTS (resemble-ai/chatterbox).
Apache 2.0 — superior ao ElevenLabs em benchmarks de naturalidade.
Preserva voz masculina melhor que XTTS v2.
Roda 100% em CPU (Ryzen 5500 compatível).
"""

import os
import re
import logging
import tempfile
from pathlib import Path
from typing import List

import numpy as np
from pydub import AudioSegment
from pydub.effects import compress_dynamic_range, normalize

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[ChatterboxNarrator] %(message)s")

# Pausas mais curtas — ritmo de podcast/YouTube
_PAUSAS_MS = {
    ".": 120,
    "!": 100,
    "?": 110,
    ";": 80,
    ":": 70,
    ",": 40,
}
_PAUSA_DEFAULT_MS = 80


class ChatterboxNarrator:
    """
    Narrador usando Chatterbox TTS com clonagem de voz zero-shot.
    API compatível com TTSNarrator para troca direta no pipeline.
    """

    def __init__(self, config: dict):
        self.config = config
        self.tts_cfg = config.get("tts", {})
        self.speed = float(self.tts_cfg.get("speed", 1.0))

        # Parâmetros Chatterbox
        cb_cfg = self.tts_cfg.get("chatterbox", {})
        self.exaggeration = float(cb_cfg.get("exaggeration", 0.5))
        self.cfg_weight    = float(cb_cfg.get("cfg_weight", 0.5))

        voice_sample = self.tts_cfg.get("voice_sample", None)
        self.voice_sample = str(Path(voice_sample).resolve()) if voice_sample else None
        self.modo_clonagem = bool(self.voice_sample and Path(self.voice_sample).is_file())

        if self.modo_clonagem:
            log.info(f"Modo clonagem ATIVO: {self.voice_sample}")
        else:
            log.info("Modo clonagem INATIVO — usando voz padrão do Chatterbox")

        self._model = None

    def _get_model(self):
        if self._model is not None:
            return self._model

        try:
            from chatterbox.tts import ChatterboxTTS
            log.info("Carregando Chatterbox TTS (primeira vez: baixa ~600MB)...")
            self._model = ChatterboxTTS.from_pretrained(device="cpu")
            log.info("Chatterbox TTS carregado!")
            return self._model
        except ImportError:
            raise ImportError(
                "Chatterbox TTS não instalado. Execute:\n"
                "  .venv/bin/pip install chatterbox-tts"
            )

    # ──────────────────────────────────────────────────────────────────────
    # Pré-processamento de texto
    # ──────────────────────────────────────────────────────────────────────

    def _limpar_texto(self, texto: str) -> str:
        texto = re.sub(r'[^\x00-\x7F\u00C0-\u024F\u1E00-\u1EFF]', '', texto)
        texto = re.sub(r'\[.*?\]', '', texto)
        texto = re.sub(r'\([A-ZÁÀÃÂÉÊÍÓÕÔÚÇ][^)]{0,40}\)', '', texto)
        texto = re.sub(
            r'(?<=[.!?])\s+(?:Ponto|Pausa|Silêncio|Fim|Pronto)\.(?=\s+[A-ZÁÀÃÂÉÊÍ])',
            '', texto
        )
        texto = re.sub(r'\*+|#+|_{2,}|`+', '', texto)
        texto = re.sub(r'\s+', ' ', texto)
        return texto.strip()

    def _expandir_abreviacoes(self, texto: str) -> str:
        subs = [
            (r'\bDr\.(?=\s)', 'Doutor '),
            (r'\bDra\.(?=\s)', 'Doutora '),
            (r'\bProf\.(?=\s)', 'Professor '),
            (r'\betc\.', 'etcetera'),
            (r'\bvs\.', 'versus'),
            (r'(\d+)\s*km\b', r'\1 quilômetros'),
            (r'(\d+)\s*kg\b', r'\1 quilogramas'),
            (r'(\d+)\s*%', r'\1 por cento'),
            (r'(\d+)\s*°C', r'\1 graus Celsius'),
        ]
        for pattern, repl in subs:
            texto = re.sub(pattern, repl, texto, flags=re.IGNORECASE)
        return texto

    def _numeros_por_extenso(self, texto: str) -> str:
        try:
            from num2words import num2words
            def _conv(m):
                try:
                    val = int(m.group(0))
                    return m.group(0) if val >= 1000 else num2words(val, lang='pt_BR')
                except Exception:
                    return m.group(0)
            texto = re.sub(r'(?<![,.\d])\b([1-9]\d{0,2})\b(?![.,\d])', _conv, texto)
        except ImportError:
            pass
        return texto

    def _preparar_texto(self, texto: str) -> str:
        texto = self._limpar_texto(texto)
        texto = self._expandir_abreviacoes(texto)
        texto = self._numeros_por_extenso(texto)
        texto = re.sub(r'\.{2,}', '.', texto)
        texto = re.sub(r'\s*--\s*', ', ', texto)
        texto = re.sub(r'\s+', ' ', texto)
        return texto.strip()

    def _dividir_em_sentencas(self, texto: str, max_chars: int = 200) -> List[str]:
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

    # ──────────────────────────────────────────────────────────────────────
    # Síntese
    # ──────────────────────────────────────────────────────────────────────

    def _sintetizar_sentenca(self, model, sentenca: str, output_path: str):
        import torchaudio

        kwargs = {
            "exaggeration": self.exaggeration,
            "cfg_weight":   self.cfg_weight,
        }
        if self.modo_clonagem:
            kwargs["audio_prompt_path"] = self.voice_sample

        wav = model.generate(sentenca, **kwargs)
        torchaudio.save(output_path, wav, model.sr)

    def _pausa_por_pontuacao(self, sentenca: str) -> AudioSegment:
        ultimo = sentenca.rstrip()[-1] if sentenca.rstrip() else '.'
        ms = _PAUSAS_MS.get(ultimo, _PAUSA_DEFAULT_MS)
        return AudioSegment.silent(duration=ms)

    def _pos_processar(self, audio: AudioSegment) -> AudioSegment:
        try:
            from scipy import signal as sp_signal
            samples = np.array(audio.get_array_of_samples(), dtype=np.float64)
            sr = audio.frame_rate
            max_val = float(2 ** (audio.sample_width * 8 - 1))
            nyq = sr / 2.0
            b, a = sp_signal.butter(2, 60.0 / nyq, btype='high')
            filtered = sp_signal.filtfilt(b, a, samples / max_val)
            out = np.clip(filtered * max_val, -max_val, max_val - 1).astype(np.int16)
            audio = audio._spawn(out.tobytes())
        except Exception as e:
            log.warning(f"High-pass não aplicado: {e}")

        audio = normalize(audio)
        audio = compress_dynamic_range(audio, threshold=-22.0, ratio=2.2, attack=8.0, release=80.0)
        gain = -16.0 - audio.dBFS
        audio = audio.apply_gain(min(gain, 6.0))
        audio = audio.fade_in(20).fade_out(80)
        return audio

    # ──────────────────────────────────────────────────────────────────────
    # API pública (compatível com TTSNarrator)
    # ──────────────────────────────────────────────────────────────────────

    def sintetizar_cena(self, texto: str, output_path: str) -> str:
        model = self._get_model()
        texto = self._preparar_texto(texto)

        if not texto:
            AudioSegment.silent(duration=1000).export(output_path, format="wav")
            return output_path

        sentencas = self._dividir_em_sentencas(texto)
        modo_label = "[clonagem]" if self.modo_clonagem else "[padrão]"
        log.info(f"Sintetizando {len(sentencas)} sentença(s) {modo_label}...")

        segmentos: List[tuple] = []
        for i, sent in enumerate(sentencas):
            log.info(f"  [{i+1}/{len(sentencas)}] {sent[:70]}{'…' if len(sent) > 70 else ''}")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                self._sintetizar_sentenca(model, sent, tmp_path)
                seg = AudioSegment.from_wav(tmp_path)
                seg = seg.fade_in(8).fade_out(12)
                segmentos.append((sent, seg))
            except Exception as e:
                log.error(f"  Erro na sentença {i+1}: {e}")
                segmentos.append((sent, AudioSegment.silent(duration=500)))
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        audio_final = AudioSegment.empty()
        for idx, (sent, seg) in enumerate(segmentos):
            audio_final += seg
            if idx < len(segmentos) - 1:
                audio_final += self._pausa_por_pontuacao(sent)

        audio_final = self._pos_processar(audio_final)
        audio_final.export(output_path, format="wav")
        log.info(f"Áudio salvo: {output_path} ({len(audio_final)/1000:.1f}s)")
        return output_path

    def sintetizar_roteiro_completo(self, roteiro_texto: str, output_path: str) -> str:
        return self.sintetizar_cena(roteiro_texto, output_path)

    def sintetizar_por_cenas(self, cenas: list, pasta_output: str) -> List[str]:
        os.makedirs(pasta_output, exist_ok=True)
        audios = []
        for cena in cenas:
            audio_path = os.path.join(pasta_output, f"cena_{cena.numero:02d}.wav")
            log.info(f"Sintetizando cena {cena.numero}: {cena.titulo}")
            self.sintetizar_cena(cena.naracao, audio_path)
            audios.append(audio_path)
        return audios
