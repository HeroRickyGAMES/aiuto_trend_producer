#!/bin/bash
echo "🚀 Configurando IA Video Creator..."

# Verificar Python
python3 --version || { echo "❌ Python3 não encontrado"; exit 1; }

# Verificar ffmpeg
ffmpeg -version > /dev/null 2>&1 || {
    echo "📦 Instalando ffmpeg..."
    sudo apt update && sudo apt install ffmpeg -y
}

# Instalar dependências
echo "📦 Instalando dependências Python..."
pip install -r requirements.txt

echo ""
echo "✅ Setup concluído!"
echo ""
echo "⚙️  PRÓXIMOS PASSOS:"
echo "   1. Instale o Ollama: https://ollama.ai"
echo "   2. Baixe um modelo: ollama pull llama3"
echo "   3. Obtenha a API key do Pexels: https://www.pexels.com/api/"
echo "   4. Configure o config.yaml com sua chave do Pexels"
echo "   5. Execute: python main.py"
