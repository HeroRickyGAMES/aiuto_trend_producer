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

    def _nome_arquivo_cache(self, query: str, tipo: str, idx: int, salt: str = "") -> str:
        nome_safe = "".join(c if c.isalnum() else "_" for c in query)[:30]
        ext = "mp4" if tipo == "video" else "jpg"
        sufixo = f"_{salt}" if salt else ""
        return os.path.join(self.pasta_cache, f"{tipo}_{nome_safe}_{idx}{sufixo}.{ext}")

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

    def buscar_imagens(self, queries, quantidade: int = 3) -> List[str]:
        """
        Busca imagens no Pexels e retorna caminhos locais.
        `queries` pode ser uma string ou uma lista de termos (keywords da cena).
        Usa página aleatória para trazer resultados diferentes a cada execução.
        """
        if isinstance(queries, str):
            queries = [queries]
        queries = [q for q in queries if q]
        arquivos = []

        for q in queries:
            if len(arquivos) >= quantidade:
                break

            page = random.randint(1, 4)
            log.info(f"Buscando imagens: '{q}' (page {page})")
            data = self._fazer_request(PEXELS_PHOTOS_URL, {
                "query": q,
                "per_page": quantidade + 3,
                "orientation": "landscape",
                "size": "large",
                "page": page,
            })

            # Se a página aleatória veio vazia, tenta a primeira página
            if not data or not data.get("photos"):
                data = self._fazer_request(PEXELS_PHOTOS_URL, {
                    "query": q, "per_page": quantidade + 3,
                    "orientation": "landscape", "size": "large", "page": 1,
                })
            if not data or not data.get("photos"):
                continue

            fotos = data["photos"]
            random.shuffle(fotos)
            for i, foto in enumerate(fotos):
                if len(arquivos) >= quantidade:
                    break
                img_url = foto["src"].get("large2x") or foto["src"].get("large")
                destino = self._nome_arquivo_cache(q, "imagem", i, salt=f"p{page}")
                if self._baixar_arquivo(img_url, destino):
                    arquivos.append(destino)

            time.sleep(0.5)

        log.info(f"Imagens obtidas: {len(arquivos)}")
        return arquivos

    def buscar_videos(self, queries, quantidade: int = 2) -> List[str]:
        """
        Busca vídeos no Pexels e retorna caminhos locais.
        `queries` pode ser string ou lista. Prefere HD landscape e varia a página.
        """
        if isinstance(queries, str):
            queries = [queries]
        queries = [q for q in queries if q]
        arquivos = []

        for q in queries:
            if len(arquivos) >= quantidade:
                break

            page = random.randint(1, 4)
            log.info(f"Buscando videos: '{q}' (page {page})")
            data = self._fazer_request(PEXELS_VIDEOS_URL, {
                "query": q,
                "per_page": quantidade + 3,
                "orientation": "landscape",
                "size": "large",
                "page": page,
            })

            if not data or not data.get("videos"):
                data = self._fazer_request(PEXELS_VIDEOS_URL, {
                    "query": q, "per_page": quantidade + 3,
                    "orientation": "landscape", "size": "large", "page": 1,
                })
            if not data or not data.get("videos"):
                continue

            videos = data["videos"]
            random.shuffle(videos)
            for i, video in enumerate(videos):
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
                    destino = self._nome_arquivo_cache(q, "video", i, salt=f"p{page}")
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
            keywords = [k for k in (cena.palavras_chave_midia or []) if k] or ["science technology"]

            # Usa TODAS as keywords da cena como candidatas (mais variedade, sem fallback genérico fixo)
            imagens = self.buscar_imagens(keywords, quantidade=4)
            videos = self.buscar_videos(keywords, quantidade=2)

            midia_por_cena[cena.numero] = {
                "imagens": imagens,
                "videos": videos,
                "query_usada": keywords[0]
            }

        return midia_por_cena
