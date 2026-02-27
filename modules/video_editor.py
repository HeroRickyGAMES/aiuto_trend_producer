"""
video_editor.py
Monta o vídeo final combinando áudio TTS + imagens/vídeos Pexels.
Usa moviepy (CPU only) — herdado do ia_dubla_animes.
"""

import os
import logging
import numpy as np
from pathlib import Path
from typing import List, Optional
from pydub import AudioSegment

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[VideoEditor] %(message)s")


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

            # Duração da cena baseada no áudio
            if audio_path and os.path.exists(audio_path):
                duracao_cena = self._calcular_duracao_audio(audio_path)
            else:
                duracao_cena = self.duracao_por_imagem * 3
                audio_path = None

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
            if audio_path and os.path.exists(audio_path):
                audio_cena = mp["AudioFileClip"](audio_path)
                clip_cena = clip_cena.with_audio(audio_cena)

            # Fade in/out na cena
            if self.transicao > 0:
                clip_cena = clip_cena.with_effects([
                    mp["FadeIn"](self.transicao),
                    mp["FadeOut"](self.transicao),
                ])

            clips_finais.append(clip_cena)
            log.info(f"  Cena {cena.numero} montada: {clip_cena.duration:.1f}s")

        # Concatena todas as cenas
        log.info("Concatenando todas as cenas...")
        video_final = mp["concatenate_videoclips"](clips_finais, method="compose")

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

        video_final.write_videofile(
            output_path,
            fps=self.fps,
            codec="libx264",
            audio_codec="aac",
            threads=os.cpu_count(),
            preset="medium",
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
