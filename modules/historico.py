"""
historico.py
Anti-repetição de conteúdo em duas camadas:
1. Histórico local (exato): registra cada vídeo gerado (URL + título) e remove
   da lista as trends que já viraram vídeo. Sem chave, sem dependência.
2. Sincronização com o YouTube (fuzzy): lê os títulos do canal (RSS = 15 últimos
   ou yt-dlp = catálogo completo) e descarta trends semelhantes a vídeos já
   publicados. Cobre uploads manuais, mas o casamento é aproximado.
"""

import os
import re
import json
import time
import shutil
import logging
import subprocess
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Palavras genéricas demais para servirem de sinal de semelhança
_STOPWORDS = {
    "the", "and", "for", "with", "you", "are", "this", "that", "from", "what",
    "how", "why", "more", "your", "our", "new", "now", "all", "out", "про",
    "para", "com", "que", "uma", "dos", "das", "como", "mais", "sobre", "todos",
    "show", "video", "videos", "parte", "final",
}


class Historico:
    def __init__(self, config: dict):
        self.config = config
        export_dir = config.get("output", {}).get("pasta", "export")
        os.makedirs(export_dir, exist_ok=True)
        self.path = os.path.join(export_dir, "_historico.json")
        self.cache_canal = os.path.join(export_dir, "_canal_titulos.json")

        ch = config.get("channel", {})
        self.youtube_url = (ch.get("youtube_url") or "").strip()

        tr = config.get("trends", {})
        self.dedup_local = tr.get("dedup_historico", True)
        self.dedup_youtube = tr.get("dedup_youtube", True)
        self.full_scan = tr.get("youtube_full_scan", False)
        self.cache_horas = tr.get("dedup_cache_horas", 24)
        # "llm" = llama raciocina semelhança (resolve EN×PT); "tokens" = comparação por palavras (rápida, mesmo idioma)
        self.dedup_metodo = tr.get("dedup_metodo", "llm")

        llm = config.get("llm", {})
        self._llm_url = llm.get("base_url", "http://localhost:11434").rstrip("/") + "/v1/chat/completions"
        self._llm_model = llm.get("model", "llama3")

        self._registros = self._carregar()
        self._urls = {r["url"] for r in self._registros if r.get("url")}
        self._titulos_norm = {r["titulo_norm"] for r in self._registros if r.get("titulo_norm")}
        self._yt_tokens = None  # lazy

    # ────────────────────────── histórico local ──────────────────────────
    def _carregar(self) -> list:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _salvar(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._registros, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning(f"Não foi possível salvar o histórico: {e}")

    def registrar(self, trend, slug: str = "", titulo_video: str = ""):
        """Registra um vídeo gerado para que a trend não se repita no futuro."""
        url_norm = self._norm_url(getattr(trend, "url", ""))
        titulo = getattr(trend, "titulo", "")
        self._registros.append({
            "url": url_norm,
            "titulo": titulo,
            "titulo_norm": self._norm_txt(titulo),
            "titulo_video": titulo_video,
            "fonte": getattr(trend, "fonte", ""),
            "slug": slug,
            "data": time.strftime("%Y-%m-%d %H:%M"),
        })
        if url_norm:
            self._urls.add(url_norm)
        self._titulos_norm.add(self._norm_txt(titulo))
        self._salvar()

    def ja_feito(self, url: str = "", titulo: str = "") -> bool:
        """Checagem barata (histórico local) — usada antes de baixar o artigo."""
        if not self.dedup_local:
            return False
        if url and self._norm_url(url) in self._urls:
            return True
        if titulo and self._norm_txt(titulo) in self._titulos_norm:
            return True
        return False

    # ────────────────────────── normalização ──────────────────────────
    @staticmethod
    def _norm_url(url: str) -> str:
        if not url:
            return ""
        try:
            p = urlparse(url.strip().lower())
            base = (p.netloc + p.path).replace("www.", "")
            return base.rstrip("/")
        except Exception:
            return url.strip().lower()

    @staticmethod
    def _norm_txt(t: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (t or "").lower())).strip()

    def _tokens(self, t: str) -> set:
        return {w for w in self._norm_txt(t).split() if len(w) > 3 and w not in _STOPWORDS}

    # ────────────────────────── camada YouTube ──────────────────────────
    def _titulos_youtube(self) -> list:
        """Títulos do canal, com cache em disco para não rebuscar a cada run."""
        cache = self._ler_cache()
        if cache is not None:
            return cache
        titulos = self._buscar_titulos_canal()
        self._gravar_cache(titulos)
        return titulos

    def _ler_cache(self):
        try:
            with open(self.cache_canal, encoding="utf-8") as f:
                data = json.load(f)
            idade_h = (time.time() - data.get("ts", 0)) / 3600.0
            if idade_h <= self.cache_horas:
                return data.get("titulos", [])
        except Exception:
            pass
        return None

    def _gravar_cache(self, titulos: list):
        try:
            with open(self.cache_canal, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "titulos": titulos}, f, ensure_ascii=False)
        except Exception:
            pass

    def _resolver_channel_id(self) -> str:
        try:
            r = requests.get(self.youtube_url, headers={"User-Agent": _UA}, timeout=20)
            r.raise_for_status()
            m = (re.search(r'"channelId":"(UC[\w-]{22})"', r.text)
                 or re.search(r"channel/(UC[\w-]{22})", r.text))
            return m.group(1) if m else ""
        except Exception as e:
            log.warning(f"Não consegui resolver o canal do YouTube: {e}")
            return ""

    def _via_rss(self) -> list:
        cid = self._resolver_channel_id()
        if not cid:
            return []
        try:
            url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
            r = requests.get(url, headers={"User-Agent": _UA}, timeout=20)
            r.raise_for_status()
            titulos = re.findall(r"<title>(.*?)</title>", r.text)
            return titulos[1:] if titulos else []  # [0] é o nome do canal
        except Exception as e:
            log.warning(f"Falha ao ler RSS do canal: {e}")
            return []

    def _via_ytdlp(self) -> list:
        if not shutil.which("yt-dlp"):
            log.info("yt-dlp não encontrado — usando RSS (15 últimos).")
            return []
        try:
            url = self.youtube_url.rstrip("/")
            if not url.endswith("/videos"):
                url += "/videos"
            out = subprocess.run(
                ["yt-dlp", "--flat-playlist", "--print", "%(title)s", url],
                capture_output=True, text=True, timeout=120
            )
            if out.returncode == 0:
                return [l.strip() for l in out.stdout.splitlines() if l.strip()]
            log.warning(f"yt-dlp retornou erro: {out.stderr[:200]}")
        except Exception as e:
            log.warning(f"yt-dlp falhou: {e}")
        return []

    def _buscar_titulos_canal(self) -> list:
        if not self.youtube_url:
            return []
        log.info("Sincronizando títulos do canal do YouTube...")
        titulos = self._via_ytdlp() if self.full_scan else []
        if not titulos:
            titulos = self._via_rss()
        log.info(f"Canal: {len(titulos)} títulos carregados para dedup.")
        return titulos

    def _carregar_yt_tokens(self):
        if self._yt_tokens is None:
            if self.dedup_youtube and self.youtube_url:
                self._yt_tokens = [tk for t in self._titulos_youtube() if (tk := self._tokens(t))]
            else:
                self._yt_tokens = []
        return self._yt_tokens

    def _parecido_com_canal(self, titulo: str) -> bool:
        """Comparação por palavras (Python). Rápida, mas só casa no MESMO idioma."""
        tt = self._tokens(titulo)
        if len(tt) < 2:
            return False
        for yt in self._carregar_yt_tokens():
            inter = tt & yt
            if len(inter) >= 2 and len(inter) / len(tt) >= 0.6:
                return True
        return False

    def _duplicatas_llm(self, trends: list, titulos: list):
        """
        Pergunta ao llama, numa única chamada curta, quais trends JÁ têm vídeo no canal.
        Resolve a divergência EN×PT (casa por significado, não por palavra).
        Retorna set de índices (em `trends`) ou None se a chamada falhar (→ fallback tokens).
        """
        titulos = [t for t in titulos if t][:60]
        if not titulos or not trends:
            return set()

        lista_canal = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titulos))
        lista_novas = "\n".join(f"{i+1}. {t.titulo}" for i, t in enumerate(trends))
        prompt = (
            "Você compara IDEIAS DE VÍDEO novas com os vídeos que um canal JÁ publicou, "
            "para evitar repetir assunto. Os idiomas podem diferir (inglês x português): "
            "compare pelo SIGNIFICADO, não pelas palavras.\n\n"
            "Regra: é DUPLICATA quando trata do MESMO assunto específico (mesmo jogo, série, "
            "produto, notícia ou projeto) — inclusive partes/episódios diferentes da MESMA série "
            "contam como já coberto. Ser apenas do mesmo gênero amplo (ex.: ambos sobre games) NÃO é duplicata.\n\n"
            f"VÍDEOS JÁ PUBLICADOS NO CANAL:\n{lista_canal}\n\n"
            f"IDEIAS NOVAS (candidatas):\n{lista_novas}\n\n"
            "Responda APENAS com um array JSON dos NÚMEROS das IDEIAS NOVAS que são duplicatas "
            "de algum vídeo já publicado. Exemplo: [2, 5]. Se nenhuma for duplicata, responda []."
        )
        try:
            resp = requests.post(self._llm_url, json={
                "model": self._llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False, "temperature": 0, "max_tokens": 200,
            }, timeout=60)
            resp.raise_for_status()
            txt = resp.json()["choices"][0]["message"]["content"]
            m = re.search(r"\[[\d,\s]*\]", txt)
            nums = json.loads(m.group()) if m else []
            return {int(n) - 1 for n in nums if 1 <= int(n) <= len(trends)}
        except Exception as e:
            log.warning(f"Dedup via llama falhou ({e}) — usando comparação por palavras.")
            return None

    # ────────────────────────── filtro final ──────────────────────────
    def filtrar(self, trends: list) -> list:
        """Remove trends já feitas (histórico) ou semelhantes a vídeos do canal."""
        if not trends:
            return trends

        # Etapa 1 — histórico local (exato, por URL/título)
        estagio = []
        removidas = 0
        for t in trends:
            if self.ja_feito(getattr(t, "url", ""), getattr(t, "titulo", "")):
                log.info(f"Já virou vídeo (histórico) — fora: {t.titulo[:55]}")
                removidas += 1
                continue
            estagio.append(t)

        # Etapa 2 — comparação com o canal do YouTube (união das duas técnicas)
        if self.dedup_youtube and self.youtube_url and estagio:
            titulos = self._titulos_youtube()
            if titulos:
                # Tokens: barato e certeiro p/ mesmo idioma (literal). Sempre roda.
                dups = {i for i, t in enumerate(estagio) if self._parecido_com_canal(t.titulo)}
                # LLM: semântico, resolve inglês×português. Soma ao resultado (None = falhou, ignora).
                if self.dedup_metodo == "llm":
                    llm_dups = self._duplicatas_llm(estagio, titulos)
                    if llm_dups:
                        dups |= llm_dups
                if dups:
                    for i in sorted(dups):
                        log.info(f"Já existe no canal — fora: {estagio[i].titulo[:55]}")
                    removidas += len(dups)
                    estagio = [t for i, t in enumerate(estagio) if i not in dups]

        if removidas:
            log.info(f"Anti-repetição: {removidas} trend(s) removida(s).")
        return estagio
