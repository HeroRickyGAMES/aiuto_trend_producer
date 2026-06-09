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

# Headers de navegador real — muitos sites (NYT, GameSpot, UnrealEngine...) devolvem
# 403 para User-Agents que parecem bot. Imitar um Chrome recente recupera boa parte.
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


@dataclass
class Trend:
    titulo: str
    fonte: str
    score: float
    descricao: str = ""
    url: str = ""
    sugestoes_busca: List[str] = field(default_factory=list)


class TrendHunter:
    def __init__(self, config: dict, historico=None):
        self.config = config
        self.historico = historico
        self.trends_cfg = config.get("trends", {})
        self.apis_cfg = config.get("apis", {})
        self.niche = config.get("channel", {}).get("niche", "tendências")
        # Tradução do título via LLM (GPU) — desligada por padrão: o roteiro final já sai em PT-BR
        self.traduzir = self.trends_cfg.get("traduzir_titulos", False)
        # Leitor via proxy (Jina Reader) p/ contornar anti-bot/paywall quando o fetch direto falha
        self.leitor_proxy = self.trends_cfg.get("leitor_proxy", True)
        llm = config.get("llm", {})
        self._ollama_url = llm.get("base_url", "http://localhost:11434") + "/v1/chat/completions"
        self._ollama_model = llm.get("model", "gemma2")

    def _traduzir_se_ingles(self, titulo: str, descricao: str) -> tuple[str, str]:
        # Pula a tradução por GPU quando desativada (padrão) — evita processamento inútil
        if not self.traduzir:
            return titulo, descricao
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
                "/no_think\n"
                "Traduza para português brasileiro de forma natural e direta. "
                "Retorne APENAS a tradução no mesmo formato (Título: ... / Descrição: ...), sem explicações.\n\n"
                + "\n".join(partes)
            )
            resp = requests.post(
                self._ollama_url,
                json={"model": self._ollama_model,
                      "messages": [{"role": "user", "content": prompt}],
                      "stream": False, "temperature": 0.1, "max_tokens": 300,
                      "chat_template_kwargs": {"enable_thinking": False}},
                timeout=30
            )
            resp.raise_for_status()
            resultado = resp.json()["choices"][0]["message"]["content"].strip()

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

    def _extrair_texto_html(self, html: str, limite: int = 3000) -> str:
        """Remove tags/scripts e devolve o texto limpo do HTML, truncado."""
        if not html:
            return ""
        html = re.sub(r"(?is)<(script|style|nav|header|footer|aside|form)[^>]*>.*?</\1>", " ", html)
        texto = re.sub(r"(?s)<[^>]+>", " ", html)
        texto = re.sub(r"&[a-z]+;", " ", texto)
        texto = re.sub(r"\s+", " ", texto).strip()
        return texto[:limite]

    def _ler_artigo(self, url: str) -> str:
        """
        Lê o texto de um artigo em camadas:
        1. fetch direto com headers de navegador (rápido, serve p/ sites abertos);
        2. se bloquear (403/anti-bot), tenta o Jina Reader (renderiza server-side).
        Retorna texto limpo ou "" (aí o roteiro usa o contexto alternativo do HN/RSS).
        """
        txt, morto = self._fetch_direto(url)
        if txt:
            return txt
        if morto:
            return ""  # link morto (404/410): proxy não recupera o que não existe mais
        if self.leitor_proxy:
            return self._fetch_jina(url)
        return ""

    def _fetch_direto(self, url: str):
        """
        Fetch direto com headers de navegador. Tenta 2x no timeout.
        Retorna (texto, link_morto): link_morto=True em 404/410 (descartável, nem tenta proxy).
        """
        for tentativa in range(2):
            try:
                resp = requests.get(url, headers=BROWSER_HEADERS, timeout=15)
                resp.raise_for_status()
                ctype = resp.headers.get("content-type", "")
                if "html" in ctype or "text" in ctype or not ctype:
                    txt = self._extrair_texto_html(resp.text, 3500)
                    if len(txt) > 200:
                        return txt, False
                return "", False
            except requests.Timeout:
                if tentativa == 0:
                    continue
                log.warning(f"Timeout no fetch direto: {url}")
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else 0
                if code in (404, 410):
                    log.info(f"Link morto ({code}): {url}")
                    return "", True
                log.info(f"Fetch direto bloqueado ({code}) — tentando leitor proxy: {url}")
            except Exception as e:
                log.warning(f"Falha no fetch direto {url}: {e}")
            break
        return "", False

    def _fetch_jina(self, url: str) -> str:
        """Fallback via Jina Reader (https://r.jina.ai) — contorna anti-bot/Cloudflare."""
        try:
            resp = requests.get(
                "https://r.jina.ai/" + url,
                headers={"User-Agent": BROWSER_HEADERS["User-Agent"], "X-Return-Format": "text"},
                timeout=25,
            )
            resp.raise_for_status()
            body = resp.text or ""
            # Remove o preâmbulo de metadados do Jina (Title:/URL Source:/...) e markdown de links/imagens
            body = re.sub(r"(?m)^(Title|URL Source|Markdown Content|Published Time|Image \d+):.*$", " ", body)
            body = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", body)
            body = re.sub(r"\s+", " ", body).strip()
            if len(body) > 200:
                log.info(f"Artigo recuperado via leitor proxy: {url}")
                return body[:3500]
        except Exception as e:
            log.warning(f"Leitor proxy falhou ({url}): {e}")
        return ""

    def _buscar_conteudo(self, url: str = "", object_id: str = "") -> str:
        """
        Lê o conteúdo REAL para enriquecer o roteiro:
        - texto do artigo na URL externa;
        - texto da postagem + principais comentários (quando vem do Hacker News).
        Retorna string concatenada (pode ser longa) ou vazia se nada for obtido.
        """
        partes = []

        if url and url.startswith("http"):
            txt = self._ler_artigo(url)
            if txt:
                partes.append(f"CONTEÚDO DO ARTIGO:\n{txt}")

        if object_id:
            try:
                resp = requests.get(
                    f"https://hn.algolia.com/api/v1/items/{object_id}", timeout=12
                )
                resp.raise_for_status()
                item = resp.json()
                story_text = self._extrair_texto_html(item.get("text") or "", 1800)
                if story_text:
                    partes.append(f"TEXTO DA POSTAGEM:\n{story_text}")
                comentarios = sorted(
                    (item.get("children") or []),
                    key=lambda c: (c.get("points") or 0), reverse=True
                )[:5]
                coment_txt = [
                    f"- {t}" for c in comentarios
                    if (t := self._extrair_texto_html(c.get("text") or "", 400))
                ]
                if coment_txt:
                    partes.append("PRINCIPAIS COMENTÁRIOS DA COMUNIDADE:\n" + "\n".join(coment_txt))
            except Exception as e:
                log.warning(f"Falha ao ler discussão HN {object_id}: {e}")

        return "\n\n".join(partes)

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
                    url_artigo = hit.get("url", "")
                    obj_id = str(hit.get("objectID", ""))
                    if self.historico and self.historico.ja_feito(url_artigo, title_trad):
                        log.info(f"Já virou vídeo — pulando: {title[:50]}")
                        continue
                    log.info(f"Lendo conteúdo real: {title[:60]}...")
                    conteudo = self._buscar_conteudo(url_artigo, obj_id)
                    if not conteudo:
                        log.info(f"Sem conteúdo (link morto/bloqueado e sem discussão) — fora da lista: {title[:50]}")
                        continue
                    descricao = f"HN — {points} pontos | {query}\n\n{conteudo}"
                    trends.append(Trend(
                        titulo=title_trad[:100],
                        fonte="hackernews",
                        score=min(100, points / 10),
                        descricao=descricao,
                        url=url_artigo,
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
                    if self.historico and self.historico.ja_feito(link, title_trad):
                        log.info(f"Já virou vídeo — pulando: {title[:50]}")
                        continue
                    conteudo = self._buscar_conteudo(link) if link else ""
                    # Sem artigo E sem um resumo aproveitável do feed = vídeo raso → fora da lista
                    if not conteudo and len((desc_trad or "").strip()) < 40:
                        log.info(f"Sem conteúdo aproveitável — fora da lista: {title[:50]}")
                        continue
                    descricao_full = desc_trad or title_trad
                    if conteudo:
                        descricao_full = f"{descricao_full}\n\n{conteudo}"
                    trends.append(Trend(
                        titulo=title_trad[:100],
                        fonte=f"rss/{fonte}",
                        score=max(10, 85 - i * 5),
                        descricao=descricao_full,
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
        # Anti-repetição: remove trends já feitas / já existentes no canal (camada YouTube)
        if self.historico:
            todas = self.historico.filtrar(todas)
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
