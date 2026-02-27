"""
metadata_gen.py
Salva título, descrição, tags e metadados do vídeo na pasta export.
"""

import os
import json
import logging
from datetime import datetime
from dataclasses import dataclass, field
from typing import List

log = logging.getLogger(__name__)


@dataclass
class Metadados:
    titulo: str
    descricao: str
    tags: List[str]
    thumb_texto: str
    tema: str
    fonte_trend: str
    data_criacao: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))
    duracao_estimada_min: float = 0.0


class MetadataGen:
    def __init__(self, config: dict):
        self.config = config
        self.canal = config.get("roteiro", {}).get("canal_nome", "Meu Canal")

    def _formatar_descricao(self, meta: Metadados) -> str:
        """Formata a descrição completa para YouTube."""
        tags_str = " ".join(f"#{t.replace(' ', '')}" for t in meta.tags[:10])
        desc = f"""{meta.descricao}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 Assunto: {meta.tema}
📅 Publicado em: {meta.data_criacao.split()[0]}
⏱️ Duração: ~{meta.duracao_estimada_min:.0f} minutos
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔔 INSCREVA-SE no canal {self.canal} e ative o sininho!
👍 Deixe seu LIKE se o vídeo foi útil!
💬 Comente sua opinião sobre o assunto!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{tags_str}

#CienciaTecnologia #Ciencia #Tecnologia #Educacao"""
        return desc

    def salvar(
        self,
        meta: Metadados,
        pasta_output: str,
        prefixo: str = "video"
    ) -> dict:
        """
        Salva todos os metadados na pasta de output.
        Retorna dict com caminhos dos arquivos criados.
        """
        os.makedirs(pasta_output, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"{prefixo}_{ts}"

        arquivos_criados = {}

        # --- titulo.txt ---
        titulo_path = os.path.join(pasta_output, f"{base}_titulo.txt")
        with open(titulo_path, "w", encoding="utf-8") as f:
            f.write(meta.titulo)
        arquivos_criados["titulo"] = titulo_path

        # --- descricao.txt ---
        desc_formatada = self._formatar_descricao(meta)
        desc_path = os.path.join(pasta_output, f"{base}_descricao.txt")
        with open(desc_path, "w", encoding="utf-8") as f:
            f.write(desc_formatada)
        arquivos_criados["descricao"] = desc_path

        # --- tags.txt ---
        tags_path = os.path.join(pasta_output, f"{base}_tags.txt")
        with open(tags_path, "w", encoding="utf-8") as f:
            # Formato para copiar direto no YouTube
            f.write(",".join(meta.tags))
        arquivos_criados["tags"] = tags_path

        # --- metadata.json (tudo junto) ---
        json_path = os.path.join(pasta_output, f"{base}_metadata.json")
        meta_dict = {
            "titulo": meta.titulo,
            "descricao_completa": desc_formatada,
            "tags": meta.tags,
            "thumb_texto": meta.thumb_texto,
            "tema": meta.tema,
            "fonte_trend": meta.fonte_trend,
            "data_criacao": meta.data_criacao,
            "duracao_minutos": meta.duracao_estimada_min,
            "canal": self.canal,
            "arquivos": arquivos_criados
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta_dict, f, ensure_ascii=False, indent=2)
        arquivos_criados["json"] = json_path

        log.info(f"Metadados salvos em {pasta_output}/")
        return arquivos_criados

    def exibir_resumo(self, meta: Metadados):
        print("\n" + "="*62)
        print("  METADADOS GERADOS")
        print("="*62)
        print(f"  Titulo   : {meta.titulo}")
        print(f"  Thumb    : {meta.thumb_texto}")
        print(f"  Tags     : {', '.join(meta.tags[:6])}...")
        titulo_len = len(meta.titulo)
        print(f"  SEO      : Titulo com {titulo_len} chars "
              f"({'OK' if titulo_len <= 60 else 'LONGO - considere encurtar'})")
        print("="*62)
