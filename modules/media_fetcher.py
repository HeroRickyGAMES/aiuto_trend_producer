"""
media_fetcher.py
Busca imagens e vídeos no Pexels API.
"""

import os
import requests
import logging
import time
import random
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[MediaFetcher] %(message)s")

PEXELS_PHOTOS_URL = "https://api.pexels.com/v1/search"
PEXELS_VIDEOS_URL = "https://api.pexels.com/videos/search"


class MediaFetcher:
    def __init__(self, config: dict):
        self.config = config
        self.api_key = (
            config.get("apis", {}).get("pexels_api_key", "")
            or config.get("media", {}).get("pexels_api_key", "")
        )
        self.pasta_cache = "assets/media_cache"
        os.makedirs(self.pasta_cache, exist_ok=True)

        if not self.api_key or "SUA_CHAVE" in self.api_key:
            raise ValueError(
                "Chave Pexels nao configurada!\n"
                "Obtenha gratuitamente em: https://www.pexels.com/api/\n"
                "Adicione no config.yaml em apis.pexels_api_key"
            )

        self.headers = {"Authorization": self.api_key}

    def _fazer_request(self, url: str, params: dict) -> Optional[dict]:
        """Request com retry automático."""
        for tentativa in range(3):
            try:
                resp = requests.get(url, headers=self.headers, params=params, timeout=15)
                if resp.status_code == 429:
                    wait = 10 * (tentativa + 1)
                    log.warning(f"Rate limit Pexels. Aguardando {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as e:
                log.warning(f"Tentativa {tentativa+1}/3 falhou: {e}")
                time.sleep(2)
        return None

    def _nome_arquivo_cache(self, query: str, tipo: str, idx: int) -> str:
        nome_safe = "".join(c if c.isalnum() else "_" for c in query)[:30]
        ext = "mp4" if tipo == "video" else "jpg"
        return os.path.join(self.pasta_cache, f"{tipo}_{nome_safe}_{idx}.{ext}")

    def _baixar_arquivo(self, url: str, destino: str) -> bool:
        """Baixa um arquivo de mídia."""
        if os.path.exists(destino) and os.path.getsize(destino) > 1000:
            log.info(f"Cache hit: {os.path.basename(destino)}")
            return True
        try:
            log.info(f"Baixando: {os.path.basename(destino)}")
            resp = requests.get(url, stream=True, timeout=30)
            resp.raise_for_status()
            with open(destino, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            log.error(f"Erro ao baixar {url}: {e}")
            return False

    def buscar_imagens(self, query: str, quantidade: int = 3) -> List[str]:
        """
        Busca imagens no Pexels e retorna lista de caminhos locais.
        Tenta queries alternativas se a principal não tiver resultados.
        """
        queries_tentar = [query, f"{query} science", "technology innovation", "science research"]
        arquivos = []

        for q in queries_tentar:
            if len(arquivos) >= quantidade:
                break

            log.info(f"Buscando imagens: '{q}'")
            data = self._fazer_request(PEXELS_PHOTOS_URL, {
                "query": q,
                "per_page": quantidade + 2,
                "orientation": "landscape",
                "size": "large"
            })

            if not data or not data.get("photos"):
                continue

            for i, foto in enumerate(data["photos"]):
                if len(arquivos) >= quantidade:
                    break
                img_url = foto["src"].get("large2x") or foto["src"].get("large")
                destino = self._nome_arquivo_cache(q, "imagem", i)
                if self._baixar_arquivo(img_url, destino):
                    arquivos.append(destino)

            time.sleep(0.5)

        log.info(f"Imagens obtidas: {len(arquivos)}")
        return arquivos

    def buscar_videos(self, query: str, quantidade: int = 2) -> List[str]:
        """
        Busca vídeos no Pexels e retorna lista de caminhos locais.
        Prefere vídeos HD em landscape.
        """
        queries_tentar = [query, f"{query} timelapse", "technology abstract", "science visualization"]
        arquivos = []

        for q in queries_tentar:
            if len(arquivos) >= quantidade:
                break

            log.info(f"Buscando videos: '{q}'")
            data = self._fazer_request(PEXELS_VIDEOS_URL, {
                "query": q,
                "per_page": quantidade + 2,
                "orientation": "landscape",
                "size": "large"
            })

            if not data or not data.get("videos"):
                continue

            for i, video in enumerate(data["videos"]):
                if len(arquivos) >= quantidade:
                    break

                # Pega o melhor arquivo HD disponível
                video_url = None
                for vf in sorted(video.get("video_files", []),
                                 key=lambda x: x.get("width", 0), reverse=True):
                    if vf.get("width", 0) >= 1280 and vf.get("file_type") == "video/mp4":
                        video_url = vf["link"]
                        break

                if not video_url and video.get("video_files"):
                    video_url = video["video_files"][0]["link"]

                if video_url:
                    destino = self._nome_arquivo_cache(q, "video", i)
                    if not destino.endswith(".mp4"):
                        destino = destino.replace(".jpg", ".mp4")
                    if self._baixar_arquivo(video_url, destino):
                        arquivos.append(destino)

            time.sleep(0.5)

        log.info(f"Videos obtidos: {len(arquivos)}")
        return arquivos

    def buscar_midia_para_cenas(self, cenas: list) -> dict:
        """
        Busca mídia para cada cena do roteiro.
        Retorna dict: {numero_cena: {"imagens": [...], "videos": [...]}}
        """
        midia_por_cena = {}

        for cena in cenas:
            log.info(f"Buscando midia para cena {cena.numero}: {cena.titulo}")
            keywords = cena.palavras_chave_midia

            # Usa a primeira keyword como primária e as outras como fallback
            query_principal = keywords[0] if keywords else "science technology"
            query_alternativa = keywords[1] if len(keywords) > 1 else "innovation"

            imagens = self.buscar_imagens(query_principal, quantidade=3)
            if not imagens:
                imagens = self.buscar_imagens(query_alternativa, quantidade=3)

            videos = self.buscar_videos(query_principal, quantidade=1)

            midia_por_cena[cena.numero] = {
                "imagens": imagens,
                "videos": videos,
                "query_usada": query_principal
            }

        return midia_por_cena
