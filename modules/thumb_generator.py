"""
thumb_generator.py
Gera thumbnail profissional para o YouTube.
Usa Pillow (CPU only).
"""

import os
import logging
import textwrap
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[ThumbGen] %(message)s")

# Tamanho padrão YouTube thumbnail
THUMB_W, THUMB_H = 1280, 720


class ThumbGenerator:
    def __init__(self, config: dict):
        self.config = config
        self.thumb_cfg = config.get("thumbnail", {})
        self.fonte_path = self.thumb_cfg.get("fonte", "")
        self.cor_titulo = self.thumb_cfg.get("cor_titulo", "#FFFFFF")
        self.cor_fundo_texto = self.thumb_cfg.get("cor_fundo_texto", "#CC0000")
        self.logo_path = self.thumb_cfg.get("logo", "")

    def _hex_to_rgb(self, hex_color: str, alpha: int = 255):
        hex_color = hex_color.lstrip("#")
        r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        return (r, g, b, alpha)

    def _carregar_fonte(self, size: int) -> ImageFont.FreeTypeFont:
        """Tenta carregar fonte personalizada, senão usa padrão."""
        if self.fonte_path and os.path.exists(self.fonte_path):
            try:
                return ImageFont.truetype(self.fonte_path, size)
            except Exception:
                pass

        # Tenta fontes do sistema (Linux/Windows/Mac)
        fontes_sistema = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/impact.ttf",
        ]
        for f in fontes_sistema:
            if os.path.exists(f):
                try:
                    return ImageFont.truetype(f, size)
                except Exception:
                    continue

        return ImageFont.load_default()

    def _escolher_imagem_fundo(self, imagens_disponiveis: list) -> Optional[Image.Image]:
        """Escolhe a melhor imagem disponível como fundo."""
        for img_path in imagens_disponiveis:
            if os.path.exists(img_path):
                try:
                    img = Image.open(img_path).convert("RGB")
                    return img
                except Exception:
                    continue
        return None

    def gerar(
        self,
        titulo: str,
        thumb_texto: str,
        imagens_disponiveis: list,
        output_path: str,
        subtitulo: str = "Ciência & Tecnologia"
    ) -> str:
        """Gera thumbnail e salva no output_path."""
        log.info(f"Gerando thumbnail: {thumb_texto}")

        # --- BACKGROUND ---
        img_fundo = self._escolher_imagem_fundo(imagens_disponiveis)

        if img_fundo:
            # Redimensiona para preencher
            img_fundo = img_fundo.resize((THUMB_W, THUMB_H), Image.LANCZOS)
            # Levemente escurece para contraste com texto
            enhancer = ImageEnhance.Brightness(img_fundo)
            img_fundo = enhancer.enhance(0.55)
            # Leve blur para profundidade
            img_fundo = img_fundo.filter(ImageFilter.GaussianBlur(radius=1.5))
            thumb = img_fundo.copy()
        else:
            # Fundo gradiente tecnológico
            thumb = Image.new("RGB", (THUMB_W, THUMB_H), (10, 10, 30))
            draw_bg = ImageDraw.Draw(thumb)
            for y in range(THUMB_H):
                r = int(10 + (y / THUMB_H) * 20)
                g = int(10 + (y / THUMB_H) * 15)
                b = int(30 + (y / THUMB_H) * 50)
                draw_bg.line([(0, y), (THUMB_W, y)], fill=(r, g, b))

        draw = ImageDraw.Draw(thumb, "RGBA")

        # --- FAIXA LATERAL ESQUERDA (destaque) ---
        faixa_w = 12
        cor_faixa = self._hex_to_rgb(self.cor_fundo_texto)
        draw.rectangle([0, 0, faixa_w, THUMB_H], fill=cor_faixa)

        # --- TEXTO PRINCIPAL (thumb_texto grande) ---
        fonte_grande = self._carregar_fonte(120)
        fonte_media = self._carregar_fonte(52)
        fonte_pequena = self._carregar_fonte(36)

        # Sombra + texto principal
        texto_principal = thumb_texto.upper()
        linhas = textwrap.wrap(texto_principal, width=14)

        # Fundo semi-transparente atrás do texto
        draw.rectangle(
            [40, THUMB_H // 2 - 30, THUMB_W - 40, THUMB_H - 20],
            fill=(0, 0, 0, 160)
        )

        # Texto grande
        y_pos = THUMB_H // 2 - 10
        for linha in linhas[:2]:  # max 2 linhas
            # Sombra
            draw.text((62, y_pos + 4), linha, font=fonte_grande, fill=(0, 0, 0, 200))
            # Texto
            draw.text((60, y_pos), linha, font=fonte_grande,
                      fill=self._hex_to_rgb(self.cor_titulo))
            y_pos += 130

        # --- SUBTÍTULO ---
        draw.text((62, y_pos + 5), subtitulo, font=fonte_pequena, fill=(200, 200, 200, 230))

        # --- LOGO (se existir) ---
        if self.logo_path and os.path.exists(self.logo_path):
            try:
                logo = Image.open(self.logo_path).convert("RGBA")
                logo_h = 80
                logo_w = int(logo.width * (logo_h / logo.height))
                logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
                thumb.paste(logo, (THUMB_W - logo_w - 30, 20), logo)
            except Exception as e:
                log.warning(f"Erro ao adicionar logo: {e}")

        # --- BADGE "NOVO" no topo ---
        cor_badge = self._hex_to_rgb(self.cor_fundo_texto)
        draw.rounded_rectangle([50, 25, 200, 80], radius=10, fill=cor_badge)
        fonte_badge = self._carregar_fonte(36)
        draw.text((65, 32), "NOVO", font=fonte_badge, fill=(255, 255, 255, 255))

        # Salva
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        thumb.save(output_path, "JPEG", quality=95)
        log.info(f"Thumbnail salva: {output_path}")
        return output_path
