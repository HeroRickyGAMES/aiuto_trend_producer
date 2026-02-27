"""
main.py — IA Video Creator
Pipeline completo: Trend → Roteiro → TTS → Mídia → Vídeo → Thumb → Metadados

Uso:
  python main.py                          # modo interativo — escolhe trend manualmente
  python main.py -a                       # modo automático — processa TODAS as trends
  python main.py --tema "Buraco Negro"    # pula busca, usa tema direto
  python main.py --config meu_config.yaml
"""

import os
import re
import sys
import yaml
import logging
import argparse
import tempfile
import shutil
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from modules.trend_hunter import TrendHunter, Trend
from modules.script_writer import ScriptWriter
from modules.tts_narrator import TTSNarrator
from modules.media_fetcher import MediaFetcher
from modules.video_editor import VideoEditor
from modules.thumb_generator import ThumbGenerator
from modules.metadata_gen import MetadataGen, Metadados

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("Main")


def banner():
    print("""
╔══════════════════════════════════════════════════════════╗
║           IA VIDEO CREATOR — Ciência & Tecnologia        ║
║   Trend → Roteiro → Voz → Mídia → Vídeo → Export        ║
╚══════════════════════════════════════════════════════════╝
""")


def carregar_config(config_path: str) -> dict:
    if not os.path.exists(config_path):
        if os.path.exists("config.yaml.exemplo"):
            log.error(f"Config '{config_path}' nao encontrado!")
            log.error("Copie o config.yaml.exemplo para config.yaml e preencha suas chaves.")
        else:
            log.error(f"Arquivo de config nao encontrado: {config_path}")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def slugify(texto: str) -> str:
    """Converte título em nome seguro para pasta (sem acentos, sem espaços)."""
    texto = texto.lower().strip()
    subs = {
        'á':'a','à':'a','ã':'a','â':'a','ä':'a',
        'é':'e','ê':'e','ë':'e','è':'e',
        'í':'i','î':'i','ï':'i','ì':'i',
        'ó':'o','ô':'o','õ':'o','ö':'o','ò':'o',
        'ú':'u','û':'u','ü':'u','ù':'u',
        'ç':'c','ñ':'n',
    }
    for k, v in subs.items():
        texto = texto.replace(k, v)
    texto = re.sub(r'[^\w\s-]', '', texto)
    texto = re.sub(r'[\s]+', '_', texto).strip('_-')
    return texto[:40]


def exibir_roteiro(roteiro):
    """Exibe o resumo do roteiro gerado."""
    print("\n" + "="*62)
    print("  ROTEIRO GERADO — REVISAO")
    print("="*62)
    print(f"  Titulo : {roteiro.titulo_video}")
    print(f"  Thumb  : {roteiro.thumb_texto}")
    print(f"  Tags   : {', '.join(roteiro.tags[:6])}")
    print(f"  Cenas  : {len(roteiro.cenas)}")
    print(f"  Palavras: ~{len(roteiro.roteiro_completo.split())}")
    print()
    for cena in roteiro.cenas:
        print(f"  [{cena.numero}] {cena.titulo}")
        preview = cena.naracao[:100] + "..." if len(cena.naracao) > 100 else cena.naracao
        print(f"       {preview}")
    print()


def confirmar_roteiro(roteiro) -> bool:
    """Exibe o roteiro e pede confirmação interativa."""
    exibir_roteiro(roteiro)
    while True:
        resp = input("  Aprovar roteiro e continuar? [s/n/e=editar titulo]: ").lower().strip()
        if resp == "s":
            return True
        elif resp == "n":
            print("  Roteiro recusado. Gerando novo roteiro...")
            return False
        elif resp == "e":
            novo_titulo = input(f"  Novo titulo [{roteiro.titulo_video}]: ").strip()
            if novo_titulo:
                roteiro.titulo_video = novo_titulo
            return True
        print("  Digite s, n ou e.")


def pipeline_completo(
    config: dict,
    tema_forcado: str = None,
    pasta_temp: str = None,
    trend_objeto: Trend = None,
    auto_mode: bool = False,
    pasta_export_override: str = None,
):
    """
    Executa o pipeline completo de criação de vídeo.

    Parâmetros:
        tema_forcado       — string de tema direto (cria Trend manualmente)
        trend_objeto       — objeto Trend já pronto (usado pelo modo auto)
        auto_mode          — se True, pula todas as interações humanas
        pasta_export_override — substitui a pasta de export do config (usado no modo auto)
    """
    output_cfg = config.get("output", {})
    pasta_export = pasta_export_override or output_cfg.get("pasta", "export")
    prefixo = output_cfg.get("prefixo_arquivo", "video")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if pasta_temp is None:
        pasta_temp = tempfile.mkdtemp(prefix="ia_video_")
        limpar_temp = True
    else:
        limpar_temp = False

    os.makedirs(pasta_export, exist_ok=True)

    try:
        # ══════════════════════════════════════════════════
        # PASSO 1: TRENDS
        # ══════════════════════════════════════════════════
        trend_escolhida = None

        if trend_objeto:
            # Vem do modo auto ou de chamada direta
            trend_escolhida = trend_objeto
            log.info(f"Tema: {trend_escolhida.titulo}")
        elif tema_forcado:
            log.info(f"Tema forcado: {tema_forcado}")
            trend_escolhida = Trend(
                titulo=tema_forcado,
                fonte="manual",
                score=100,
                sugestoes_busca=[tema_forcado, f"{tema_forcado} science"]
            )
        else:
            print("\n[PASSO 1/6] Buscando trends de ciência e tecnologia...")
            hunter = TrendHunter(config)
            trend_escolhida = hunter.exibir_e_escolher()
            if not trend_escolhida:
                log.error("Nenhuma trend selecionada. Encerrando.")
                return

        # ══════════════════════════════════════════════════
        # PASSO 2: ROTEIRO
        # ══════════════════════════════════════════════════
        print(f"\n[PASSO 2/6] Gerando roteiro sobre: {trend_escolhida.titulo}")
        writer = ScriptWriter(config)

        roteiro = None

        if auto_mode:
            # Sem interação — gera o roteiro e segue
            roteiro = writer.gerar(
                tema=trend_escolhida.titulo,
                contexto=trend_escolhida.descricao
            )
            exibir_roteiro(roteiro)
            log.info("[AUTO] Roteiro aprovado automaticamente.")
        else:
            aprovado = False
            tentativas = 0
            while not aprovado and tentativas < 3:
                tentativas += 1
                roteiro = writer.gerar(
                    tema=trend_escolhida.titulo,
                    contexto=trend_escolhida.descricao
                )
                aprovado = confirmar_roteiro(roteiro)

            if not aprovado or roteiro is None:
                log.error("Roteiro nao aprovado apos 3 tentativas.")
                return

        # ══════════════════════════════════════════════════
        # PASSO 3: BUSCA DE MÍDIA
        # ══════════════════════════════════════════════════
        print(f"\n[PASSO 3/6] Buscando imagens e videos no Pexels...")
        fetcher = MediaFetcher(config)
        midia_por_cena = fetcher.buscar_midia_para_cenas(roteiro.cenas)

        todas_imagens = []
        for cena_num, midia in midia_por_cena.items():
            todas_imagens.extend(midia.get("imagens", []))

        # ══════════════════════════════════════════════════
        # PASSO 4: NARRAÇÃO TTS
        # ══════════════════════════════════════════════════
        print(f"\n[PASSO 4/6] Gerando narração com Coqui TTS...")
        narrator = TTSNarrator(config)
        pasta_audio = os.path.join(pasta_temp, "audio_cenas")
        audio_por_cena = narrator.sintetizar_por_cenas(roteiro.cenas, pasta_audio)

        # ══════════════════════════════════════════════════
        # PASSO 5: MONTAGEM DO VÍDEO
        # ══════════════════════════════════════════════════
        print(f"\n[PASSO 5/6] Montando video final...")
        video_path = os.path.join(pasta_export, f"{prefixo}_{ts}.mp4")
        editor = VideoEditor(config)
        editor.montar_video(
            cenas=roteiro.cenas,
            midia_por_cena=midia_por_cena,
            audio_por_cena=audio_por_cena,
            output_path=video_path
        )

        # ══════════════════════════════════════════════════
        # PASSO 6: THUMBNAIL + METADADOS
        # ══════════════════════════════════════════════════
        print(f"\n[PASSO 6/6] Gerando thumbnail e metadados...")

        thumb_path = os.path.join(pasta_export, f"{prefixo}_{ts}_thumb.jpg")
        thumb_gen = ThumbGenerator(config)
        thumb_gen.gerar(
            titulo=roteiro.titulo_video,
            thumb_texto=roteiro.thumb_texto,
            imagens_disponiveis=todas_imagens,
            output_path=thumb_path
        )

        duracao_min = 0
        try:
            from moviepy.editor import VideoFileClip
            with VideoFileClip(video_path) as v:
                duracao_min = v.duration / 60
        except Exception:
            duracao_min = config.get("roteiro", {}).get("duracao_alvo_minutos", 5)

        meta = Metadados(
            titulo=roteiro.titulo_video,
            descricao=roteiro.descricao_youtube,
            tags=roteiro.tags,
            thumb_texto=roteiro.thumb_texto,
            tema=trend_escolhida.titulo,
            fonte_trend=trend_escolhida.fonte,
            duracao_estimada_min=duracao_min
        )
        meta_gen = MetadataGen(config)
        arquivos_meta = meta_gen.salvar(meta, pasta_export, prefixo + f"_{ts}")
        meta_gen.exibir_resumo(meta)

        print("\n" + "="*62)
        print("  PIPELINE CONCLUIDO COM SUCESSO!")
        print("="*62)
        print(f"  Video    : {video_path}")
        print(f"  Thumb    : {thumb_path}")
        print(f"  Titulo   : {arquivos_meta.get('titulo', '')}")
        print(f"  Descricao: {arquivos_meta.get('descricao', '')}")
        print(f"  Tags     : {arquivos_meta.get('tags', '')}")
        print(f"  JSON     : {arquivos_meta.get('json', '')}")
        print("="*62)
        print(f"\n  Tudo salvo em: ./{pasta_export}/")

        return video_path

    finally:
        if limpar_temp and os.path.exists(pasta_temp):
            log.info("Limpando arquivos temporarios...")
            shutil.rmtree(pasta_temp, ignore_errors=True)


def pipeline_automatico(config: dict):
    """
    Modo -a: busca TODAS as trends e processa cada uma automaticamente.
    Sem interação humana após a confirmação inicial.
    Cada trend é exportada em export/<slug_do_tema>/
    """
    print("\n[AUTO] Buscando todas as trends disponíveis...")
    hunter = TrendHunter(config)
    trends = hunter.buscar_todas()

    if not trends:
        print("\n  Nenhuma trend encontrada pelas APIs.")
        print("  Use  python main.py --tema 'Seu Tema'  para rodar manualmente.")
        return

    # Exibe lista completa
    print("\n" + "="*62)
    print(f"  MODO AUTOMATICO — {len(trends)} TRENDS ENCONTRADAS")
    print("="*62)
    for i, t in enumerate(trends, 1):
        fonte_label = t.fonte.split("/")[-1]  # só o nome curto da fonte
        print(f"  [{i:02d}] {t.titulo}")
        print(f"       Fonte: {fonte_label}  |  Score: {t.score:.0f}")
    print("="*62)

    pasta_export_base = config.get("output", {}).get("pasta", "export")
    print(f"\n  Pasta de saída base: ./{pasta_export_base}/")
    print(f"  Cada tema terá sua própria subpasta: ./{pasta_export_base}/<tema>/")
    print()

    resp = input(f"  Iniciar processamento automático de {len(trends)} vídeos? [s/n]: ").strip().lower()
    if resp != "s":
        print("  Cancelado.")
        return

    # Processa cada trend
    resultados = []
    inicio_total = datetime.now()

    for i, trend in enumerate(trends):
        slug = slugify(trend.titulo)
        pasta_trend = os.path.join(pasta_export_base, slug)

        print("\n" + "="*62)
        print(f"  PROCESSANDO [{i+1}/{len(trends)}]: {trend.titulo}")
        print(f"  Pasta: ./{pasta_trend}/")
        print("="*62)

        inicio = datetime.now()
        try:
            pipeline_completo(
                config,
                trend_objeto=trend,
                auto_mode=True,
                pasta_export_override=pasta_trend,
            )
            duracao = datetime.now() - inicio
            resultados.append({
                "titulo": trend.titulo,
                "status": "OK",
                "pasta": pasta_trend,
                "tempo": str(duracao).split(".")[0],  # HH:MM:SS sem microssegundos
            })
            log.info(f"[AUTO] Concluído em {duracao}")

        except Exception as e:
            duracao = datetime.now() - inicio
            log.error(f"[AUTO] Erro em '{trend.titulo}': {e}")
            resultados.append({
                "titulo": trend.titulo,
                "status": f"ERRO: {e}",
                "pasta": None,
                "tempo": str(duracao).split(".")[0],
            })

    # Resumo final
    tempo_total = datetime.now() - inicio_total
    ok = [r for r in resultados if r["status"] == "OK"]
    erros = [r for r in resultados if r["status"] != "OK"]

    print("\n" + "="*62)
    print("  MODO AUTO — RESUMO FINAL")
    print("="*62)
    for r in resultados:
        icone = "✓" if r["status"] == "OK" else "✗"
        print(f"  [{icone}] {r['titulo']}")
        if r["status"] == "OK":
            print(f"        Pasta : ./{r['pasta']}/")
        else:
            print(f"        {r['status']}")
        print(f"        Tempo : {r['tempo']}")
    print("="*62)
    print(f"  Concluídos : {len(ok)}/{len(trends)}")
    if erros:
        print(f"  Com erro   : {len(erros)}")
    print(f"  Tempo total: {str(tempo_total).split('.')[0]}")
    print("="*62)


def main():
    parser = argparse.ArgumentParser(
        description="IA Video Creator — Ciência & Tecnologia"
    )
    parser.add_argument(
        "--config", default="config.yaml",
        help="Caminho para o arquivo de configuracao (default: config.yaml)"
    )
    parser.add_argument(
        "--tema", default=None,
        help="Pula busca de trend e usa este tema diretamente"
    )
    parser.add_argument(
        "-a", "--auto",
        action="store_true",
        help="Modo automático: processa TODAS as trends sem interação humana"
    )
    parser.add_argument(
        "--listar-modelos-tts", action="store_true",
        help="Lista modelos TTS disponíveis em portugues e sai"
    )
    args = parser.parse_args()

    banner()
    config = carregar_config(args.config)

    if args.listar_modelos_tts:
        narrator = TTSNarrator(config)
        narrator.listar_modelos_pt()
        return

    if args.auto:
        pipeline_automatico(config)
    else:
        pipeline_completo(config, tema_forcado=args.tema)


if __name__ == "__main__":
    main()
