#!/bin/bash
# setup_ollama.sh
# Instala e configura o Ollama com o modelo llama3

echo "=== Setup Ollama ==="

# Instala Ollama (Linux)
if ! command -v ollama &> /dev/null; then
    echo "Instalando Ollama..."
    curl -fsSL https://ollama.ai/install.sh | sh
else
    echo "Ollama já instalado."
fi

# Baixa o modelo (escolha um)
echo ""
echo "Modelos disponíveis (escolha um para baixar):"
echo "  1) llama3        (8B params, ~4.7GB, boa qualidade)"
echo "  2) mistral       (7B params, ~4.1GB, rápido)"
echo "  3) gemma2        (9B params, ~5.4GB, muito bom)"
echo "  4) phi3          (3.8B params, ~2.2GB, leve)"
read -p "Escolha [1-4]: " opcao

case $opcao in
    1) ollama pull llama3 ;;
    2) ollama pull mistral ;;
    3) ollama pull gemma2 ;;
    4) ollama pull phi3 ;;
    *) echo "Opção inválida"; exit 1 ;;
esac

echo ""
echo "Para iniciar o servidor Ollama:"
echo "  ollama serve"
echo ""
echo "Para testar:"
echo "  ollama run llama3 'Olá, tudo bem?'"
