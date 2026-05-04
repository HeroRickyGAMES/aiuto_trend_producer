"""
trend_hunter.py
Busca trends via:
- Google Trends
- Hacker News (Algolia API — sem autenticação)
- RSS feeds configuráveis via config.yaml
"""

import re
import requests
import time
import logging
import xml.etree.ElementTree as ET
from urllib.parse import quote
from pytrends.request import TrendReq
from dataclasses import dataclass, field
from typing import List, Optional

logging.basicConfig(level=logging.INFO, format="[Aiuto Trend Producer] %(message)s")
log = logging.getLogger(__name__)


@dataclass
class Trend:
    titulo: str
    fonte: str
    score: float
    descricao: str = ""
    url: str = ""
    sugestoes_busca: List[str] = field(default_factory=list)


class TrendHunter:
    def __init__(self, config: dict):
        self.config = config
        self.trends_cfg = config.get("trends", {})
        self.apis_cfg = config.get("apis", {})
        self.niche = config.get("channel", {}).get("niche", "tendências")
        llm = config.get("llm", {})
        self._ollama_url = llm.get("base_url", "http://localhost:11434") + "/api/generate"
        self._ollama_model = llm.get("model", "gemma2")

    def _traduzir_se_ingles(self, titulo: str, descricao: str) -> tuple[str, str]:
        try:
            from langdetect import detect
            texto_amostra = f"{titulo} {descricao}"[:200]
            if detect(texto_amostra) == "pt":
                return titulo, descricao
        except Exception:
            return titulo, descricao

        try:
            partes = []
            if titulo:
                partes.append(f"Título: {titulo}")
            if descricao:
                partes.append(f"Descrição: {descricao}")
            prompt = (
                "Traduza para português brasileiro de forma natural e direta. "
                "Retorne APENAS a tradução no mesmo formato (Título: ... / Descrição: ...), sem explicações.\n\n"
                + "\n".join(partes)
            )
            resp = requests.post(
                self._ollama_url,
                json={"model": self._ollama_model, "prompt": prompt, "stream": False,
                      "options": {"temperature": 0.1, "num_predict": 300}},
                timeout=30
            )
            resp.raise_for_status()
            resultado = resp.json().get("response", "").strip()

            titulo_trad = titulo
            desc_trad = descricao
            for linha in resultado.splitlines():
                if linha.lower().startswith("título:"):
                    titulo_trad = linha.split(":", 1)[1].strip()
                elif linha.lower().startswith("descrição:"):
                    desc_trad = linha.split(":", 1)[1].strip()
            return titulo_trad, desc_trad
        except Exception as e:
            log.warning(f"Tradução falhou: {e}")
            return titulo, descricao

    def buscar_google_trends(self) -> List[Trend]:
        google_cfg = self.trends_cfg.get("google_trends", {})
        if not google_cfg.get("enabled", True):
            log.info("Google Trends desativado (enabled: false no config)")
            return []

        log.info("Buscando no Google Trends...")
        trends = []
        categorias = google_cfg.get("keywords_seed", ["tecnologia"])
        regiao = google_cfg.get("geo", "BR")

        try:
            pytrends = TrendReq(hl="pt-BR", tz=180, timeout=(10, 25))

            try:
                trending_df = pytrends.trending_searches(pn="brazil")
                keywords_filter = [k.lower() for k in categorias]
                for i, row in trending_df.head(20).iterrows():
                    termo = str(row[0]).strip()
                    if any(k in termo.lower() for k in keywords_filter):
                        trends.append(Trend(
                            titulo=termo,
                            fonte="google_trending",
                            score=max(10, 90 - i * 2),
                            descricao="Trending no Google Brasil",
                            sugestoes_busca=[termo, f"{termo} news", f"{termo} 2025"]
                        ))
            except Exception as e:
                log.warning(f"trending_searches falhou ({e}). Continuando com related_queries...")

            for idx, categoria in enumerate(categorias[:3]):
                try:
                    pytrends.build_payload([categoria], cat=0, timeframe="now 7-d", geo=regiao)
                    related = pytrends.related_queries()
                    if categoria in related and related[categoria]["top"] is not None:
                        df_top = related[categoria]["top"]
                        for _, row in df_top.head(3).iterrows():
                            query = str(row["query"])
                            valor = float(row["value"])
                            trends.append(Trend(
                                titulo=query.title(),
                                fonte="google_related",
                                score=valor,
                                descricao=f"Trend relacionada a '{categoria}' (7 dias)",
                                sugestoes_busca=[query, f"{query} news", f"{query} 2025"]
                            ))
                    time.sleep(3 + idx)
                except Exception as e:
                    if "429" in str(e):
                        log.warning("Rate limit Google Trends — aguardando 5s e pulando...")
                        time.sleep(5)
                    else:
                        log.warning(f"Erro ao buscar '{categoria}': {e}")
        except Exception as e:
            log.error(f"Erro Google Trends: {e}")

        log.info(f"Google Trends: {len(trends)} encontradas")
        return trends

    def buscar_hackernews(self) -> List[Trend]:
        log.info("Buscando no Hacker News...")
        trends = []
        hn_cfg = self.trends_cfg.get("hackernews", {})
        queries = hn_cfg.get("queries", ["technology", "gaming", "science"])
        min_pts = hn_cfg.get("min_points", 50)

        for query in queries:
            try:
                url = (
                    f"https://hn.algolia.com/api/v1/search"
                    f"?query={quote(query)}&tags=story&hitsPerPage=5"
                )
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                for hit in resp.json().get("hits", []):
                    title = (hit.get("title") or "").strip()
                    points = hit.get("points") or 0
                    if points < min_pts or not title:
                        continue
                    title_trad, _ = self._traduzir_se_ingles(title, "")
                    trends.append(Trend(
                        titulo=title_trad[:100],
                        fonte="hackernews",
                        score=min(100, points / 10),
                        descricao=f"HN — {points} pontos | {query}",
                        url=hit.get("url", ""),
                        sugestoes_busca=[" ".join(title_trad.split()[:6])]
                    ))
                time.sleep(1)
            except Exception as e:
                log.warning(f"Erro Hacker News '{query}': {e}")

        log.info(f"Hacker News: {len(trends)} encontradas")
        return trends

    def buscar_rss(self) -> List[Trend]:
        log.info("Buscando feeds RSS...")
        trends = []

        feeds_cfg = self.trends_cfg.get("astronomia_rss", {}).get("feeds", [])
        if not feeds_cfg:
            log.warning("Nenhum feed RSS configurado em trends.astronomia_rss.feeds")
            return trends

        headers = {"User-Agent": "Mozilla/5.0 (compatible; ia_video_creator/1.0)"}

        for feed in feeds_cfg:
            feed_url = feed.get("url", "")
            fonte = feed.get("nome", feed_url)
            if not feed_url:
                continue
            try:
                resp = requests.get(feed_url, headers=headers, timeout=15)
                resp.raise_for_status()
                root = ET.fromstring(resp.content)

                for i, item in enumerate(root.findall(".//item")[:6]):
                    title_el = item.find("title")
                    desc_el = item.find("description")
                    link_el = item.find("link")
                    if title_el is None or not title_el.text:
                        continue
                    title = title_el.text.strip()
                    desc_raw = (desc_el.text or "") if desc_el is not None else ""
                    desc = re.sub(r"<[^>]+>", "", desc_raw).strip()[:200]
                    link = (link_el.text or "") if link_el is not None else ""
                    title_trad, desc_trad = self._traduzir_se_ingles(title, desc)
                    trends.append(Trend(
                        titulo=title_trad[:100],
                        fonte=f"rss/{fonte}",
                        score=max(10, 85 - i * 5),
                        descricao=desc_trad or title_trad,
                        url=link,
                        sugestoes_busca=[" ".join(title_trad.split()[:6])]
                    ))
                time.sleep(0.5)
            except Exception as e:
                log.warning(f"Erro RSS {fonte}: {e}")

        log.info(f"RSS: {len(trends)} encontradas")
        return trends

    def buscar_todas(self) -> List[Trend]:
        google = self.buscar_google_trends()
        hackernews = self.buscar_hackernews()
        rss = self.buscar_rss()
        todas = google + hackernews + rss
        todas.sort(key=lambda t: t.score, reverse=True)
        max_t = self.trends_cfg.get("max_trends", 15)
        return todas[:max_t]

    def _pedir_tema_manual(self) -> Optional["Trend"]:
        print("\n" + "="*62)
        print("  APIS INDISPONIVEIS — Entrada manual")
        print("="*62)
        print("  Google Trends está bloqueando as requisições.")
        print("  Você pode digitar o tema do vídeo manualmente.")
        print()
        print("  [0] Tentar buscar trends novamente")
        print("="*62)

        while True:
            tema = input("\n  Digite o tema (ou 0 para tentar de novo): ").strip()
            if tema == "0":
                return self.exibir_e_escolher()
            if tema:
                print(f"\n  Tema manual: {tema}\n")
                return Trend(
                    titulo=tema,
                    fonte="manual",
                    score=100,
                    descricao="Tema inserido manualmente pelo usuário",
                    sugestoes_busca=[tema, f"{tema} news", f"{tema} 2025"]
                )
            print("  Digite um tema ou 0 para tentar novamente.")

    def exibir_e_escolher(self) -> Optional["Trend"]:
        trends = self.buscar_todas()
        if not trends:
            log.warning("Nenhuma trend encontrada!")
            return self._pedir_tema_manual()

        print("\n" + "="*62)
        print(f"   TRENDS — {self.niche.upper()}")
        print("="*62)
        for i, t in enumerate(trends, 1):
            bar = "=" * int(t.score / 10)
            print(f"\n  [{i:02d}] {t.titulo}")
            print(f"       Fonte : {t.fonte}")
            print(f"       Score : [{bar:<10}] {t.score:.0f}")
            if t.descricao:
                desc = t.descricao[:75] + "..." if len(t.descricao) > 75 else t.descricao
                print(f"       Info  : {desc}")

        print("\n" + "="*62)
        print("  [0] Buscar novamente")
        print("  [m] Digitar tema manualmente")
        print("="*62)

        while True:
            try:
                entrada = input("\n  Numero da trend (ou m para manual): ").strip().lower()
                if entrada == "0":
                    return self.exibir_e_escolher()
                if entrada == "m":
                    return self._pedir_tema_manual()
                escolha = int(entrada)
                if 1 <= escolha <= len(trends):
                    chosen = trends[escolha - 1]
                    print(f"\n  Escolhida: {chosen.titulo}\n")
                    return chosen
                print("  Numero invalido.")
            except ValueError:
                print("  Digite um numero, 0 para rebuscar, ou m para manual.")
