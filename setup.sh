#!/bin/bash
echo "🚀 Configurando IA Video Creator..."

# Verificar Python
python3 --version || { echo "❌ Python3 não encontrado"; exit 1; }

# Verificar ffmpeg
ffmpeg -version > /dev/null 2>&1 || {
    echo "📦 Instalando ffmpeg..."
    sudo apt update && sudo apt install ffmpeg -y
}

# Criar e ativar venv
echo "🐍 Criando ambiente virtual (.venv)..."
python3 -m venv .venv
source .venv/bin/activate

# Instalar dependências
echo "📦 Instalando dependências Python..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "✅ Setup concluído!"
echo ""
echo "⚙️  PRÓXIMOS PASSOS:"
echo "   1. Ative o venv:        source .venv/bin/activate"
echo "   2. Instale o Ollama:    https://ollama.ai"
echo "   3. Baixe um modelo:     ollama pull llama3"
echo "   4. Obtenha a API key do Pexels: https://www.pexels.com/api/"
echo "   5. Configure o config.yaml com sua chave do Pexels"
echo "   6. Execute:             python main.py"
