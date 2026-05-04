"""
video_editor.py
Monta o vídeo final combinando áudio TTS + imagens/vídeos Pexels.
Suporta aceleração GPU via ffmpeg (nvenc/amf/qsv) com fallback automático para CPU.
"""

import os
import subprocess
import logging
import numpy as np
from pathlib import Path
from typing import List, Optional
from pydub import AudioSegment

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[VideoEditor] %(message)s")


def _detectar_encoder() -> tuple[str, list]:
    """
    Detecta o melhor encoder de vídeo disponível via ffmpeg.
    Retorna (codec, ffmpeg_params).
    """
    candidatos = [
        (
            "h264_nvenc",
            ["-preset", "p4", "-rc", "vbr", "-cq", "23", "-b:v", "0"],
            "NVIDIA NVENC",
        ),
        (
            "h264_amf",
            ["-quality", "speed", "-rc", "vbr_latency_hq", "-qp_i", "22", "-qp_p", "24"],
            "AMD AMF",
        ),
        (
            "h264_qsv",
            ["-preset", "faster", "-global_quality", "23"],
            "Intel Quick Sync",
        ),
    ]

    for codec, params, nome in candidatos:
        try:
            result = subprocess.run(
                ["ffmpeg", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=1",
                 "-vcodec", codec, "-f", "null", "-"],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                log.info(f"Encoder GPU detectado: {nome} ({codec})")
                return codec, params
        except Exception:
            continue

    log.info("Nenhum encoder GPU disponível — usando CPU (libx264 ultrafast)")
    return "libx264", ["-preset", "ultrafast", "-crf", "23"]


class VideoEditor:
    def __init__(self, config: dict):
        self.config = config
        self.video_cfg = config.get("video", {})
        self.resolucao = tuple(self.video_cfg.get("resolucao", [1920, 1080]))
        self.fps = self.video_cfg.get("fps", 30)
        self.duracao_por_imagem = self.video_cfg.get("duracao_por_imagem", 5)
        self.transicao = self.video_cfg.get("transicao_duracao", 0.5)
        self.vol_musica = self.video_cfg.get("volume_musica", 0.08)
        self.musica_arquivo = self.video_cfg.get("musica_arquivo", "")

        encoder_cfg = self.video_cfg.get("encoder", "auto")
        if encoder_cfg == "auto":
            self.codec, self.ffmpeg_params = _detectar_encoder()
        elif encoder_cfg == "nvenc":
            self.codec = "h264_nvenc"
            self.ffmpeg_params = ["-preset", "p4", "-rc", "vbr", "-cq", "23", "-b:v", "0"]
        elif encoder_cfg == "amf":
            self.codec = "h264_amf"
            self.ffmpeg_params = ["-quality", "speed", "-rc", "vbr_latency_hq"]
        elif encoder_cfg == "qsv":
            self.codec = "h264_qsv"
            self.ffmpeg_params = ["-preset", "faster", "-global_quality", "23"]
        else:
            self.codec = "libx264"
            self.ffmpeg_params = ["-preset", "ultrafast", "-crf", "23"]

    def _get_moviepy(self):
        """Import lazy do moviepy (pesado, só quando necessário)."""
        from moviepy import (
            VideoFileClip, ImageClip, AudioFileClip,
            CompositeAudioClip, concatenate_videoclips,
            CompositeVideoClip, ColorClip, concatenate_audioclips
        )
        from moviepy.video.fx import FadeIn, FadeOut
        from moviepy.audio.fx import AudioFadeIn, AudioFadeOut
        return {
            "VideoFileClip": VideoFileClip,
            "ImageClip": ImageClip,
            "AudioFileClip": AudioFileClip,
            "CompositeAudioClip": CompositeAudioClip,
            "concatenate_videoclips": concatenate_videoclips,
            "concatenate_audioclips": concatenate_audioclips,
            "CompositeVideoClip": CompositeVideoClip,
            "ColorClip": ColorClip,
            "FadeIn": FadeIn,
            "FadeOut": FadeOut,
            "AudioFadeIn": AudioFadeIn,
            "AudioFadeOut": AudioFadeOut,
        }

    def _calcular_duracao_audio(self, audio_path: str) -> float:
        """Retorna duração do arquivo de áudio em segundos."""
        try:
            audio = AudioSegment.from_file(audio_path)
            return len(audio) / 1000.0
        except Exception:
            return self.duracao_por_imagem * 5  # fallback

    def _criar_clip_imagem(self, mp, img_path: str, duracao: float):
        """Cria um videoclip a partir de uma imagem com zoom suave (efeito Ken Burns)."""
        clip = mp["ImageClip"](img_path).with_duration(duracao)

        # Resize para preencher a resolução
        w, h = self.resolucao
        clip = clip.resized(height=h)
        if clip.w < w:
            clip = clip.resized(width=w)

        # Centraliza
        clip = clip.with_position("center")

        # Efeito zoom suave (1.0 → 1.05)
        def zoom(t):
            scale = 1.0 + 0.05 * (t / duracao)
            return scale

        clip = clip.resized(lambda t: zoom(t))
        clip = clip.with_position("center")

        return mp["CompositeVideoClip"]([clip], size=self.resolucao).with_duration(duracao)

    def _criar_clip_video(self, mp, video_path: str, duracao: float):
        """Cria clip de vídeo com loop se necessário."""
        try:
            clip = mp["VideoFileClip"](video_path, audio=False)

            # Resize para preencher tela
            w, h = self.resolucao
            clip = clip.resized(height=h)
            if clip.w < w:
                clip = clip.resized(width=w)

            # Loop se o vídeo for menor que a duração necessária
            if clip.duration < duracao:
                import math
                loops = math.ceil(duracao / clip.duration)
                clip = mp["concatenate_videoclips"]([clip] * loops)

            clip = clip.subclipped(0, duracao)
            clip = clip.with_position("center")
            return mp["CompositeVideoClip"]([clip], size=self.resolucao).with_duration(duracao)
        except Exception as e:
            log.warning(f"Erro ao processar vídeo {video_path}: {e}")
            return None

    def montar_video(
        self,
        cenas: list,
        midia_por_cena: dict,
        audio_por_cena: List[str],
        output_path: str
    ) -> str:
        """
        Monta o vídeo final.
        - cenas: lista de objetos Cena do roteiro
        - midia_por_cena: dict {num_cena: {"imagens": [...], "videos": [...]}}
        - audio_por_cena: lista de caminhos de áudio (um por cena)
        - output_path: caminho do vídeo final .mp4
        """
        mp = self._get_moviepy()
        log.info("Iniciando montagem do video final...")

        clips_finais = []

        for i, cena in enumerate(cenas):
            audio_path = audio_por_cena[i] if i < len(audio_por_cena) else None
            midia = midia_por_cena.get(cena.numero, {})

            # Carrega o áudio primeiro para usar sua duração exata (evita cortes)
            audio_cena = None
            if audio_path and os.path.exists(audio_path):
                audio_cena = mp["AudioFileClip"](audio_path)
                duracao_cena = audio_cena.duration
            else:
                duracao_cena = self.duracao_por_imagem * 3

            log.info(f"Cena {cena.numero} '{cena.titulo}': {duracao_cena:.1f}s")

            # Escolhe mídia para esta cena
            videos_disponiveis = [v for v in midia.get("videos", []) if os.path.exists(v)]
            imagens_disponiveis = [img for img in midia.get("imagens", []) if os.path.exists(img)]

            clips_cena = []

            if videos_disponiveis:
                # Usa vídeo como base
                clip_base = self._criar_clip_video(mp, videos_disponiveis[0], duracao_cena)
                if clip_base:
                    clips_cena.append(clip_base)

            if not clips_cena and imagens_disponiveis:
                # Divide duração entre as imagens disponíveis
                n_imgs = min(len(imagens_disponiveis), 4)
                dur_img = duracao_cena / n_imgs

                for img_path in imagens_disponiveis[:n_imgs]:
                    clip_img = self._criar_clip_imagem(mp, img_path, dur_img)
                    if clip_img:
                        clips_cena.append(clip_img)

            if not clips_cena:
                # Fallback: tela preta com duração correta
                clips_cena.append(
                    mp["ColorClip"](size=self.resolucao, color=[10, 10, 30], duration=duracao_cena)
                )

            # Concatena clips da cena
            clip_cena = mp["concatenate_videoclips"](clips_cena, method="compose")
            clip_cena = clip_cena.subclipped(0, duracao_cena)

            # Adiciona áudio da narração
            if audio_cena is not None:
                clip_cena = clip_cena.with_audio(audio_cena)

            clips_finais.append(clip_cena)
            log.info(f"  Cena {cena.numero} montada: {clip_cena.duration:.1f}s")

        # Concatena todas as cenas — fade só no início e fim do vídeo inteiro
        log.info("Concatenando todas as cenas...")
        video_final = mp["concatenate_videoclips"](clips_finais, method="compose")
        if self.transicao > 0:
            video_final = video_final.with_effects([
                mp["FadeIn"](self.transicao),
                mp["FadeOut"](self.transicao),
            ])

        # Adiciona música de fundo (opcional)
        if self.video_cfg.get("musica_fundo") and os.path.exists(self.musica_arquivo):
            log.info("Adicionando musica de fundo...")
            try:
                musica = mp["AudioFileClip"](self.musica_arquivo).with_volume_scaled(self.vol_musica)

                # Loop da música se necessário
                if musica.duration < video_final.duration:
                    import math
                    n = math.ceil(video_final.duration / musica.duration)
                    musica = mp["concatenate_audioclips"]([musica] * n)

                musica = musica.subclipped(0, video_final.duration)
                musica = musica.with_effects([
                    mp["AudioFadeIn"](2),
                    mp["AudioFadeOut"](3),
                ])

                if video_final.audio:
                    audio_mix = mp["CompositeAudioClip"]([video_final.audio, musica])
                    video_final = video_final.with_audio(audio_mix)
                else:
                    video_final = video_final.with_audio(musica)
            except Exception as e:
                log.warning(f"Erro ao adicionar musica: {e}")

        # Exporta o vídeo final
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        log.info(f"Exportando video: {output_path}")
        log.info(f"Resolucao: {self.resolucao} | FPS: {self.fps} | Duracao: {video_final.duration:.1f}s")

        log.info(f"Encoder: {self.codec} | params: {self.ffmpeg_params}")
        video_final.write_videofile(
            output_path,
            fps=self.fps,
            codec=self.codec,
            audio_codec="aac",
            threads=os.cpu_count(),
            ffmpeg_params=self.ffmpeg_params,
            logger="bar"
        )

        # Limpa recursos
        video_final.close()
        for c in clips_finais:
            try:
                c.close()
            except Exception:
                pass

        log.info(f"Video exportado com sucesso: {output_path}")
        return output_path
